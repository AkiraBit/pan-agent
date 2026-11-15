from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from src.platform.persistence.database import SessionLocal
from . import sources
from .models import EtfDaily, EtfFlowDay, EtfHolding, EtfMinute, EtfSnapshot

log = logging.getLogger(__name__)
_inflight = {}
_checked = {}
_retry = {}
_worker = None
_holders_checked = -1e12


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def money(value):
    return None if value is None else round(sources.finite(value) * 1e8, 2)


def snapshot(db, resource, key, payload, source, url, updated=None):
    checksum = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    row = db.scalar(select(EtfSnapshot).where(EtfSnapshot.resource == resource, EtfSnapshot.key == key).order_by(EtfSnapshot.id.desc()))
    if row is None or row.checksum != checksum:
        row = EtfSnapshot(resource=resource, key=key, payload=payload, source=source,
                   source_url=url, source_updated_at=updated, observed_at=timestamp(), checksum=checksum)
        db.add(row)
        db.flush()
    return row


def upsert(db, model, rows, keys):
    if not rows:
        return
    statement = insert(model).values(rows)
    db.execute(statement.on_conflict_do_update(index_elements=keys,
               set_={key: getattr(statement.excluded, key) for key in rows[0] if key not in keys}))


def save_board(payload, raw):
    with SessionLocal() as db:
        snap = snapshot(db, 'board', payload['date'], raw, 'kanpanba', sources.BOARD_URL, raw.get('updated_at'))
        day = payload['date']
        rows = [{'code': r['code'], 'trade_date': day, 'name': r['name'], 'index_name': r['index'],
                 'close': r.get('close'), 'change_percent': r.get('change_percent'), 'turnover_cny': money(r.get('amount')),
                 'shares_delta': money(r.get('shares_delta')), 'net_subscription_estimate_cny': money(r.get('net')),
                 'scale_cny': money(r.get('scale')), 'peak_ratio': (r.get('peak_window') or {}).get('ratio'),
                 'snapshot_id': snap.id} for r in payload['etfs']]
        upsert(db, EtfDaily, rows, ['code', 'trade_date'])
        profile = dict(payload.get('profile') or [])
        upsert(db, EtfMinute, [{'trade_date': day, 'time': t, 'turnover_cny': money(v),
               'baseline_turnover_cny': money(profile.get(t)), 'snapshot_id': snap.id} for t, v in payload.get('minutes', [])], ['trade_date', 'time'])
        history = {r['date']: r for r in payload.get('series', [])}
        history[day] = {**history.get(day, {}), 'date': day, 'covered': payload['covered'], 'net': payload.get('net'),
                        'hs300_change_percent': payload.get('hs300_change_percent'), 'peak_window': payload.get('peak_window')}
        # Backfilling an old board must not replace a newer historical revision.
        existing = dict(db.execute(select(EtfFlowDay.trade_date, EtfSnapshot.key)
                                  .join(EtfSnapshot, EtfFlowDay.snapshot_id == EtfSnapshot.id)).all())
        upsert(db, EtfFlowDay, [{'trade_date': r['date'], 'covered': r.get('covered', 0),
              'net_subscription_estimate_cny': money(r.get('net')), 'index_close': r.get('hs300'),
              'index_change_percent': r.get('hs300_change_percent'), 'peak_ratio': (r.get('peak_window') or {}).get('ratio'),
              'snapshot_id': snap.id} for r in history.values() if existing.get(r['date'], '') <= day], ['trade_date'])
        signals = []
        for r in history.values():
            peak = r.get('peak_window') or {}
            if r.get('net') is not None and r['net'] > 0 and (peak.get('ratio') or 0) >= 2 and r.get('hs300_change_percent') is not None and r['hs300_change_percent'] < 0:
                signals.append({'date': r['date'], 'kind': 'countertrend_subscription', 'actor': None,
                                'net_subscription_estimate_cny': money(r['net']), 'peak_ratio': peak['ratio'],
                                'index_change_percent': r['hs300_change_percent'], 'covered': r.get('covered'),
                                'evidence_snapshot_id': snap.id, 'rule_version': 'countertrend-v1'})
        snapshot(db, 'signals', day, {'signals': signals, 'board_snapshot_id': snap.id}, 'panwatch', '/api/etf/national-team')
        db.commit()
        return snap.id


def saved_board(requested=None, knowledge_cutoff=None):
    with SessionLocal() as db:
        query = select(EtfSnapshot).where(EtfSnapshot.resource == 'board')
        if requested:
            query = query.where(EtfSnapshot.key == requested)
        if knowledge_cutoff:
            query = query.where(EtfSnapshot.observed_at <= knowledge_cutoff)
        snap = db.scalar(query.order_by(EtfSnapshot.key.desc(), EtfSnapshot.id.desc()))
        if not snap:
            return None
        return {'payload': sources.validate_board(snap.payload, requested), 'snapshot_id': snap.id,
                'observed_at': snap.observed_at, 'source': snap.source, 'source_url': snap.source_url}


async def coalesce(key, action):
    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(action())
        _inflight[key] = task
        def done(completed):
            if _inflight.get(key) is completed:
                _inflight.pop(key, None)
            if not completed.cancelled():
                completed.exception()  # retrieve errors even if every caller disconnected
        task.add_done_callback(done)
    return await asyncio.shield(task)


async def board(requested=None):
    if requested:
        sources.day(requested)
    key = ('board', requested)
    cached = await asyncio.to_thread(saved_board, requested)
    ttl = 300 if requested else 60
    if cached and time.monotonic() - _checked.get(key, -1e12) < ttl:
        return {**cached, 'stale': False}
    if cached and time.monotonic() < _retry.get(key, 0):
        return {**cached, 'stale': True}
    async def refresh():
        payload, raw = await sources.board(requested)
        await asyncio.to_thread(save_board, payload, raw)
        _checked[key] = time.monotonic()
        _retry.pop(key, None)
    try:
        await coalesce(key, refresh)
        return {**await asyncio.to_thread(saved_board, requested), 'stale': False}
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
        _retry[key] = time.monotonic() + 60
        if cached:
            return {**cached, 'stale': True}
        raise


async def dates():
    with SessionLocal() as db:
        cached = db.scalar(select(EtfSnapshot).where(EtfSnapshot.resource == 'dates').order_by(EtfSnapshot.id.desc()))
        saved = list(cached.payload) if cached else []
        local = list(db.scalars(select(EtfSnapshot.key).where(EtfSnapshot.resource == 'board').distinct()))
    if time.monotonic() - _checked.get(('dates',), -1e12) > 600:
        try:
            saved = await coalesce(('dates',), sources.dates)
            with SessionLocal() as db:
                snapshot(db, 'dates', 'calendar', saved, 'kanpanba', sources.DATES_URL)
                db.commit()
            _checked[('dates',)] = time.monotonic()
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            if not saved and not local:
                raise
    return sorted(set(saved + local), reverse=True)


def save_holdings(reports):
    with SessionLocal() as db:
        for report in reports:
            key = f"{report['code']}:{report['report_date']}"
            url = f"{sources.HOLDERS_URL}?symbol={report['code']}&date={report['report_date']}"
            snap = snapshot(db, 'holdings', key, report, 'sina', url)
            for holder in report['holders']:
                db.execute(insert(EtfHolding).values(snapshot_id=snap.id, code=report['code'], report_date=report['report_date'],
                           known_from=snap.observed_at, **holder).on_conflict_do_nothing())
        db.commit()


async def collect_holdings(codes):
    global _holders_checked
    if time.monotonic() - _holders_checked < 86400:
        return
    async def collect():
        gate = asyncio.Semaphore(2)
        async def one(code):
            async with gate:
                try:
                    reports = await sources.holding_reports(code)
                    await asyncio.to_thread(save_holdings, reports)
                    return True
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    log.warning('ETF holder source unavailable: %s', code)
                    return False
        outcomes = await asyncio.gather(*(one(code) for code in codes))
        global _holders_checked
        if all(outcomes):
            _holders_checked = time.monotonic()
    await coalesce(('holders',), collect)


def national_team(payload, knowledge_cutoff=None):
    """Latest reports known by cutoff; report date is never treated as publication date."""
    cutoff = knowledge_cutoff or timestamp()
    by_code = {}
    with SessionLocal() as db:
        reports = db.scalars(select(EtfSnapshot).where(EtfSnapshot.resource == 'holdings', EtfSnapshot.observed_at <= cutoff).order_by(EtfSnapshot.id.desc())).all()
        for report in reports:
            data = report.payload
            if data['report_date'] <= payload['date']:
                by_code.setdefault(data['code'], {}).setdefault(data['report_date'], report)
        holdings = []
        coverage = []
        for etf in payload['etfs']:
            code = etf['code']
            periods = sorted(by_code.get(code, {}), reverse=True)
            if not periods:
                coverage.append({'code': code, 'report_date': None})
                continue
            report = by_code[code][periods[0]]
            previous = by_code[code][periods[1]].payload if len(periods) > 1 else None
            previous_holders = {r['holder_name']: r for r in previous['holders']} if previous else {}
            coverage.append({'code': code, 'report_date': periods[0]})
            for holder in report.payload['holders']:
                if not holder['institution']:
                    continue
                old = previous_holders.get(holder['holder_name'])
                holdings.append({**holder, 'code': code, 'name': etf['name'], 'index': etf['index'],
                                 'report_date': periods[0], 'previous_report_date': periods[1] if previous else None,
                                 'shares_change': holder['shares'] - old['shares'] if old else None,
                                 'known_from': report.observed_at, 'announced_at': None,
                                 'evidence_kind': 'provider_reported_holding', 'source_url': report.source_url,
                                 'snapshot_id': report.id})
        signal_snapshot = db.scalar(select(EtfSnapshot).where(EtfSnapshot.resource == 'signals', EtfSnapshot.key == payload['date'], EtfSnapshot.observed_at <= cutoff).order_by(EtfSnapshot.id.desc()))
        signals = signal_snapshot.payload['signals'] if signal_snapshot else []
    watched = {r['code'] for r in holdings}
    watchlist = [{**r, 'disclosed_ratio': sum(h['ratio_percent'] for h in holdings if h['code'] == r['code'])} for r in payload['etfs'] if r['code'] in watched]
    return {'date': payload['date'], 'knowledge_cutoff': cutoff, 'holdings': holdings, 'coverage': coverage,
            'watchlist': watchlist, 'signals': sorted(signals, key=lambda r: r['date'], reverse=True),
            'institutions': sorted({r['institution'] for r in holdings}), 'holding_etf_count': len(watched),
            'watchlist_net_estimate_cny': sum(money(r['net']) for r in watchlist) if watchlist and all(r.get('net') is not None for r in watchlist) else None,
            'flow_attribution': 'all_etf_investors', 'rule_version': 'countertrend-v1'}


async def run_collection():
    while True:
        try:
            result = await board()
            await collect_holdings([r['code'] for r in result['payload']['etfs']])
            await dates()
            # History is backfilled gradually, with a bounded number of requests per pass.
            with SessionLocal() as db:
                have = set(db.scalars(select(EtfSnapshot.key).where(EtfSnapshot.resource == 'board')))
            missing = [d for d in await dates() if d not in have][:3]
            for date in missing:
                await board(date)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('ETF collection failed; saved observations retained')
        await asyncio.sleep(60)


async def start():
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(run_collection())


async def stop():
    global _worker
    tasks = list(_inflight.values()) + ([_worker] if _worker else [])
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _inflight.clear()
    _worker = None
