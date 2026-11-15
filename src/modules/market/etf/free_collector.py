"""Source-controlled, restartable public ETF ingestion and rolling-year backfill."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import select

from . import free_sources as adapters, free_store as store, service, sources, turnover
from .models import EtfDaily, EtfMeasurement

MAX_JOBS = 32


def spans(start, end, size=179):
    current, stop = date.fromisoformat(start), date.fromisoformat(end)
    while current <= stop:
        last = min(stop, current + timedelta(days=size))
        yield current.isoformat(), last.isoformat()
        current = last + timedelta(days=1)


def inputs():
    with service.SessionLocal() as db:
        rows = db.scalars(select(EtfMeasurement)).all()
        daily = {(r.code, r.trade_date): {
            'missing': r.shares_delta is None or r.net_subscription_estimate_cny is None or r.scale_cny is None,
            'close': r.close} for r in db.scalars(select(EtfDaily))}
        return {(r.resource, r.source, r.code, r.trade_date): r.payload for r in rows}, daily


async def collect(start=None, *, max_jobs=MAX_JOBS):
    async def run():
        ctx = await asyncio.to_thread(store.context)
        if not ctx:
            return 0
        active = set(await asyncio.to_thread(store.settings))
        if not active:
            return 0
        first = min(start or ctx['start'], ctx['start'])
        sources.day(first)
        end = turnover.last_closed_day()
        baseline = (date.fromisoformat(first) - timedelta(days=14)).isoformat()
        codes = list(ctx['universe'])
        used, written = 0, 0
        failures = {}

        async def job(kind, provider, key, fetch, *, expected=None, ttl=3600):
            nonlocal used, written
            if used >= max_jobs or (kind, provider) not in active or not await asyncio.to_thread(store.due, key):
                return
            if not await asyncio.to_thread(store.enabled, kind, provider):
                active.discard((kind, provider)); return
            used += 1
            try:
                async with adapters.Client(lambda: store.enabled(kind, provider)) as client:
                    batch = await fetch(client)
                written += await asyncio.to_thread(store.save, batch, key, expected=expected, ttl=ttl)
            except asyncio.CancelledError:
                raise
            except adapters.Disabled:
                active.discard((kind, provider))
            except Exception as exc:
                pair = (kind, provider)
                failures[pair] = failures.get(pair, 0) + 1
                if failures[pair] >= 2:
                    active.discard(pair)
                resource = adapters.SPECS[pair][0]
                await asyncio.to_thread(store.failure, key, resource, provider, exc)
                service.log.warning('Public ETF source unavailable: %s/%s (%s)', kind, provider, type(exc).__name__)

        # Index prices supply actual trading dates; never fill weekends with zeros.
        for c in ['000300', *codes]:
            for lo, hi in spans(baseline, end, 499):
                await job('etf_history', 'tencent', f'price:tencent:{c}:{lo}:{hi}',
                          lambda client, c=c, lo=lo, hi=hi: adapters.prices(client, c, lo, hi))
        for c in codes:
            await job('etf_nav', 'eastmoney', f'nav:eastmoney:{c}:{baseline}:{end}',
                      lambda client, c=c: adapters.nav(client, c, baseline, end), ttl=21600)

        measurements, daily = await asyncio.to_thread(inputs)
        calendars = {c: sorted({d for (r, s, code, d) in measurements if r == 'price' and code == c}
            | {d for (code, d), row in daily.items() if code == c and row['close'] is not None}) for c in codes}
        recent = (datetime.now(sources.CN).date() - timedelta(days=7)).isoformat()
        # The previous evening's shares are provisional until the next morning.
        now = datetime.now(sources.CN)
        share_end = (now.date() - timedelta(days=1 if now.hour >= 9 else 2)).isoformat()
        required = {}
        for c, days in calendars.items():
            wanted = set()
            for i, d in enumerate(days):
                if not first <= d <= share_end:
                    continue
                current = daily.get((c, d))
                if current is None or current['missing'] or d >= recent:
                    wanted.add(d)
                    if i:
                        wanted.add(days[i - 1])
            required[c] = wanted
        for c in (c for c in codes if c.startswith('15')):
            wanted = required[c]
            if not wanted:
                continue
            for lo, hi in spans(min(wanted), max(wanted)):
                expected = {(c, d) for d in wanted if lo <= d <= hi}
                if expected:
                    await job('etf_shares', 'szse', f'shares:szse:{c}:{lo}:{hi}',
                              lambda client, c=c, lo=lo, hi=hi: adapters.szse_shares(client, c, lo, hi),
                              expected=expected, ttl=3600 if hi >= recent else 30 * 86400)
        sh_codes = {c for c in codes if c.startswith('5')}
        sh_days = sorted({d for c in sh_codes for d in required[c]}, reverse=True)
        for d in sh_days:
            await job('etf_shares', 'sse', f'shares:sse:{d}',
                      lambda client, d=d: adapters.sse_shares(client, d, sh_codes),
                      expected={(c, d) for c in sh_codes if d in required[c]},
                      ttl=3600 if d >= recent else 30 * 86400)

        for c in codes:
            calendar = calendars[c]
            if not calendar:
                continue
            provider = 'szse' if c.startswith('15') else 'sse'
            candidates = [calendar[-1]]
            if provider == 'szse':
                missing_nav = [calendar[i + 1] for i, d in enumerate(calendar[:-1]) if d >= first
                    and ('nav', 'eastmoney', c, d) not in measurements
                    and not any(k[0] == 'pcf' and k[2] == c and v.get('nav_date') == d for k, v in measurements.items())]
                candidates += missing_nav[:2]
            for d in dict.fromkeys(candidates):
                await job('etf_pcf', provider, f'pcf:{provider}:{c}:{d}',
                          lambda client, c=c, d=d, p=provider: adapters.pcf(client, p, c, d), ttl=21600)
        # Rebuild also after restart between committing inputs and materialization.
        await asyncio.to_thread(store.rebuild, first)
        return written
    return await service.coalesce(('free-etf',), run)


async def test_source(source, symbols):
    """Exercise exactly the configured provider, with the same parser/persistence."""
    from src.modules.market.data_collector import CollectorResult
    kind, provider = source.type, source.provider
    if not source.enabled:
        return CollectorResult(success=False, error='数据源未启用')
    spec = adapters.SPECS.get((kind, provider))
    if not spec:
        return CollectorResult(success=False, error='不支持的 ETF 数据源')
    ctx = await asyncio.to_thread(store.context)
    end = ctx['end'] if ctx else turnover.last_closed_day()
    start = (date.fromisoformat(end) - timedelta(days=14)).isoformat()
    results, errors = [], []
    for c in symbols[:4]:
        key = f'test:{spec[0]}:{provider}:{c}:{end}'
        try:
            async with adapters.Client(lambda: store.enabled(kind, provider)) as client:
                if kind == 'etf_shares':
                    if provider == 'szse':
                        batch = await adapters.szse_shares(client, c, start, end)
                    else:
                        adapters.code(c)
                        if not c.startswith('5'):
                            raise adapters.InvalidData('unsupported_sse_code')
                        batch = await adapters.sse_shares(client, end, {c})
                elif kind == 'etf_nav':
                    batch = await adapters.nav(client, c, start, end)
                elif kind == 'etf_history':
                    batch = await adapters.prices(client, c, start, end)
                else:
                    batch = await adapters.pcf(client, provider, c, end)
            await asyncio.to_thread(store.save, batch, key)
            results.extend([{k: v for k, v in r.items() if k not in {'components', 'header'}} |
                            ({'components_count': len(r['components'])} if 'components' in r else {}) for r in batch.rows])
        except Exception as exc:
            await asyncio.to_thread(store.failure, key, spec[0], provider, exc)
            errors.append({'symbol': c, 'market': 'CN', 'error': str(exc) if isinstance(exc, adapters.InvalidData) else '数据源暂不可用'})
    if results:
        await asyncio.to_thread(store.rebuild)
    return CollectorResult(success=bool(results) and not errors, data=results[:100], count=len(results), errors=errors,
                           error='部分标的数据不完整' if errors and results else '未获取到有效数据' if not results else '')
