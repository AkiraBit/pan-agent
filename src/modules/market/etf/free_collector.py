"""Source-controlled, restartable public ETF ingestion and rolling-year backfill."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from . import free_sources as adapters, free_store as store, service, sources, turnover

MAX_JOBS = 32


def spans(start, end, size=179):
    current, stop = date.fromisoformat(start), date.fromisoformat(end)
    while current <= stop:
        last = min(stop, current + timedelta(days=size))
        yield current.isoformat(), last.isoformat()
        current = last + timedelta(days=1)


async def collect(start=None, *, max_jobs=MAX_JOBS):
    async def run():
        ctx = await asyncio.to_thread(store.context)
        if not ctx:
            return 0
        settings = await asyncio.to_thread(store.settings)
        active = set(settings)
        if not active:
            return 0
        first = min(start or ctx['start'], ctx['start'])
        sources.day(first)
        end = turnover.last_closed_day()
        baseline = (date.fromisoformat(first) - timedelta(days=14)).isoformat()
        codes = list(ctx['universe'])
        used, written = 0, 0
        failures = {}

        async def job(kind, provider, key, fetch, *, ttl=3600):
            nonlocal used, written
            if used >= max_jobs or (kind, provider) not in active or not await asyncio.to_thread(store.due, key):
                return
            if not await asyncio.to_thread(store.enabled, kind, provider):
                active.discard((kind, provider)); return
            used += 1
            try:
                async with adapters.Client(lambda: store.enabled(kind, provider)) as client:
                    batch = await fetch(client)
                written += await asyncio.to_thread(store.save, batch, key, ttl=ttl)
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
        for c in (*adapters.BENCHMARK_CODES, *codes):
            for lo, hi in spans(baseline, end, 499):
                await job('etf_history', 'tencent', f'price:tencent:{c}:{lo}:{hi}',
                          lambda client, c=c, lo=lo, hi=hi: adapters.prices(client, c, lo, hi))
        for c in codes:
            for kind, provider in settings:
                if kind != 'etf_nav':
                    continue
                await job(kind, provider, f'nav:{provider}:{c}:{baseline}:{end}',
                          lambda client, c=c, p=provider: adapters.fuyao_nav(c, baseline, end) if p == 'fuyao'
                          else adapters.nav(client, c, baseline, end), ttl=21600)

        # Rebuild also after restart between committing inputs and materialization.
        await asyncio.to_thread(store.rebuild, first)
        return written
    return await service.coalesce(('free-etf',), run)


async def test_source(source, symbols):
    """Exercise exactly the configured provider, with the same parser/persistence."""
    from src.modules.market.data_collector import CollectorResult, _probe_value
    kind, provider = source.type, source.provider
    if not source.enabled:
        return CollectorResult(success=False, error='数据源未启用')
    spec = adapters.SPECS.get((kind, provider))
    if not spec:
        return CollectorResult(success=False, error='不支持的 ETF 数据源')
    ctx = await asyncio.to_thread(store.context)
    end = ctx['end'] if ctx else turnover.last_closed_day()
    start = (date.fromisoformat(end) - timedelta(days=_probe_value(source, "lookback_days", 14))).isoformat()
    results, errors = [], []
    for c in symbols[:4]:
        key = f'test:{spec[0]}:{provider}:{c}:{end}'
        try:
            async with adapters.Client(lambda: store.enabled(kind, provider)) as client:
                if kind == 'etf_nav':
                    batch = await (adapters.fuyao_nav(c, start, end) if provider == 'fuyao' else adapters.nav(client, c, start, end))
                else:
                    batch = await adapters.prices(client, c, start, end)
            await asyncio.to_thread(store.save, batch, key)
            results.extend(batch.rows)
        except Exception as exc:
            await asyncio.to_thread(store.failure, key, spec[0], provider, exc)
            errors.append({'symbol': c, 'market': 'CN', 'error': str(exc) if isinstance(exc, adapters.InvalidData) else '数据源暂不可用'})
    if results:
        await asyncio.to_thread(store.rebuild)
    return CollectorResult(success=bool(results) and not errors, data=results[:100], count=len(results), errors=errors,
                           error='部分标的数据不完整' if errors and results else '未获取到有效数据' if not results else '')
