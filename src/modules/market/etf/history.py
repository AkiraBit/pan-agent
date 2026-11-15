"""Date-range research views rebuilt from immutable, persisted ETF observations."""
from __future__ import annotations

import asyncio
import calendar
import time
from datetime import date

import httpx
from sqlalchemy import func, select

from . import free_collector, free_store, service, sources, turnover
from .models import EtfSnapshot

PROVIDER_ERRORS = (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError)


def months_before(day, months):
    value = date.fromisoformat(day)
    year, month = divmod(value.year * 12 + value.month - 1 - months, 12)
    month += 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])).isoformat()


def latest_snapshots(db, resource, cutoff=None):
    query = select(func.max(EtfSnapshot.id)).where(EtfSnapshot.resource == resource)
    if cutoff:
        query = query.where(EtfSnapshot.observed_at <= cutoff)
    return db.scalars(select(EtfSnapshot).where(EtfSnapshot.id.in_(query.group_by(EtfSnapshot.key)))
                      .order_by(EtfSnapshot.key)).all()


def stored_dates(cutoff=None):
    with service.SessionLocal() as db:
        boards = latest_snapshots(db, 'board', cutoff)
        catalogs = latest_snapshots(db, 'dates', cutoff)
        return sorted({day for snapshot in catalogs for day in snapshot.payload}
                      | {snapshot.key for snapshot in boards} | set(free_store.saved_dates(db, cutoff)))


async def fill_boards(days):
    """Bound each backfill and share individual requests with the daily collector."""
    with service.SessionLocal() as db:
        have = set(db.scalars(select(EtfSnapshot.key).where(EtfSnapshot.resource == 'board')))
        catalogs = latest_snapshots(db, 'dates')
        supported = {d for s in catalogs for d in s.payload}
    missing = [day for day in reversed(days) if day not in have and (not catalogs or day in supported)][:240]
    gate = asyncio.Semaphore(3)

    async def one(day):
        async with gate:
            if time.monotonic() < service._retry.get(('board', day), 0):
                return
            try:
                await service.board(day)
            except PROVIDER_ERRORS:
                service.log.warning('ETF historical board unavailable: %s', day)
    await asyncio.gather(*(one(day) for day in missing))


async def fill_reports(codes, start, end):
    gate = asyncio.Semaphore(2)

    async def one(code):
        async with gate:
            key = ('holding-history', code, start, end)
            if time.monotonic() - service._checked.get(key, -1e12) < 86400:
                return
            if time.monotonic() < service._retry.get(key, 0):
                return
            try:
                periods = [p for p in await sources.holding_periods(code) if p <= end]
                # Include two prior reports to anchor the range and compare the baseline.
                requested = [p for p in periods if p >= start] + [p for p in periods if p < start][:2]
                with service.SessionLocal() as db:
                    have = set(db.scalars(select(EtfSnapshot.key).where(EtfSnapshot.resource == 'holdings')))
                for period in requested:
                    if f'{code}:{period}' not in have:
                        report = await sources.holding_report(code, period)
                        await asyncio.to_thread(service.save_holdings, [report])
                service._checked[key] = time.monotonic()
            except PROVIDER_ERRORS:
                service._retry[key] = time.monotonic() + 60
                service.log.warning('ETF historical holdings unavailable: %s', code)
    await asyncio.gather(*(one(code) for code in codes))


async def collect_range(days, codes, start, end, national, public_start=None):
    tasks = [fill_boards(days)]
    if national:
        tasks.append(fill_reports(codes, start, end))
    await asyncio.gather(*tasks)
    await free_collector.collect(public_start)
    await turnover.collect()


def complete_sum(values):
    return sum(values) if values and all(value is not None for value in values) else None


def observed_sum(values):
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def holding_history(reports, codes, institution, start, end):
    by_code = {}
    for snapshot in reports:
        report = snapshot.payload
        if report['code'] in codes and report['report_date'] <= end:
            by_code.setdefault(report['code'], {})[report['report_date']] = snapshot
    periods = sorted({period for items in by_code.values() for period in items})
    prior = [period for period in periods if period < start]
    selected = {period for period in periods if period >= start} | set(prior[-1:])
    points, details = [], []
    for period in periods:
        if period not in selected:
            continue
        shares, reported, matched_codes, ids = [], [], set(), []
        for code, items in by_code.items():
            if period not in items:
                continue
            snapshot = items[period]
            reported.append(code)
            ids.append(snapshot.id)
            older = sorted(p for p in items if p < period)
            old = items[older[-1]].payload if older else None
            old_holders = {h['holder_name']: h for h in old['holders']} if old else {}
            for holder in snapshot.payload['holders']:
                if not holder['institution'] or (institution and holder['institution'] != institution):
                    continue
                matched_codes.add(code)
                shares.append(holder['shares'])
                previous = old_holders.get(holder['holder_name'])
                details.append({**holder, 'code': code, 'name': codes[code]['name'], 'index': codes[code]['index'],
                                'report_date': period, 'announced_at': None,
                                'previous_report_date': older[-1] if older else None,
                                'shares_change': holder['shares'] - previous['shares'] if previous else None,
                                'snapshot_id': snapshot.id, 'known_from': snapshot.observed_at,
                                'source_url': snapshot.source_url})
        # A missing top-ten entry is not a zero holding. Coverage changes break the line.
        total = sum(shares) / 1e8 if shares and len(reported) == len(codes) else None
        points.append({'date': period, 'shares': total, 'reported_shares': sum(shares) / 1e8 if shares else None,
                       'held_funds': len(matched_codes), 'reported_funds': len(reported), 'expected_funds': len(codes),
                       'before_range': period < start, 'snapshot_ids': ids})
    watched = set()
    composition = []
    for code, items in by_code.items():
        period = max(items)
        snapshot = items[period]
        if any(h['institution'] and (not institution or h['institution'] == institution) for h in snapshot.payload['holders']):
            watched.add(code)
            composition.append({'code': code, 'report_date': period, 'snapshot_id': snapshot.id})
    return points, sorted(details, key=lambda r: (r['report_date'], r['code']), reverse=True), watched, composition


def read_history(start, end, catalog, *, national=False, code=None, institution=None, cutoff=None):
    with service.SessionLocal() as db:
        boards = latest_snapshots(db, 'board', cutoff)
        reports = latest_snapshots(db, 'holdings', cutoff) if national else []
        if not boards:
            raise ValueError('No saved ETF observations')
        universe = {r['code']: r for r in boards[-1].payload['etfs']}
        if code and code not in universe:
            raise ValueError('Unknown ETF code')
        selected = {c: r for c, r in universe.items() if not code or c == code}
        report_points, disclosures, watched, composition = holding_history(reports, selected, institution, start, end)
        target = watched if national else set(selected)
        # Prefer the newest board containing a day, independent of backfill arrival order.
        aggregate, daily = {}, {}
        supplements = turnover.observations(db, cutoff)
        public = free_store.derived(db, cutoff)
        for snapshot in boards:
            payload = turnover.overlay(free_store.overlay(sources.validate_board(snapshot.payload), public), supplements)
            for point in payload.get('series', []):
                aggregate[point['date']] = {**point, 'snapshot_id': snapshot.id}
            point = aggregate.get(payload['date'], {})
            aggregate[payload['date']] = {**point, 'date': payload['date'], 'net': payload.get('net'),
                                        'covered': payload['covered'], 'peak_window': payload.get('peak_window'),
                                        'hs300_change_percent': payload.get('hs300_change_percent'), 'snapshot_id': snapshot.id}
            daily[payload['date']] = (payload, snapshot.id)
        for day in {d for (c, d) in public if c in universe} - daily.keys():
            payload = free_store.synthetic(day, universe, public)
            if payload:
                daily[day] = (turnover.overlay(payload, supplements), None)
        # Reapply corrected daily aggregates after all provider history revisions.
        for day, (payload, snapshot_id) in daily.items():
            if payload.get('net_source') == free_store.METHOD or payload.get('source') == 'public_sources':
                aggregate[day] = {**aggregate.get(day, {}), 'date': day, 'net': payload.get('net'),
                    'covered': payload['covered'], 'hs300': payload.get('hs300') or aggregate.get(day, {}).get('hs300'),
                    'hs300_change_percent': payload.get('hs300_change_percent'),
                    'peak_window': payload.get('peak_window'), 'snapshot_id': snapshot_id}
            elif payload.get('hs300') is not None:
                aggregate[day].setdefault('hs300', payload['hs300'])
        days = sorted(day for day in set(catalog) | set(daily) if start <= day <= end)
        series, fund_values = [], {c: [] for c in target}
        cumulative, cumulative_days = 0, 0
        for day in days:
            baseline = aggregate.get(day, {})
            payload, snapshot_id = daily.get(day, ({}, None))
            rows = [r for r in payload.get('etfs', []) if r['code'] in target]
            for row in rows:
                fund_values[row['code']].append((day, row))
            full = bool(target) and len(rows) == len(target)
            basket = not national and not code
            net = baseline.get('net') if basket else complete_sum([r.get('net') for r in rows]) if full else None
            amount = payload.get('amount') if basket else complete_sum([r.get('amount') for r in rows]) if full else None
            scale = payload.get('scale') if basket else complete_sum([r.get('scale') for r in rows]) if full else None
            if net is not None:
                cumulative += net
                cumulative_days += 1
            ratio = max((r.get('peak_window', {}).get('ratio') or 0 for r in rows if r.get('peak_window')), default=0) if not basket else (baseline.get('peak_window') or {}).get('ratio')
            series.append({'date': day, 'net': net, 'amount': amount, 'scale': scale,
                           'cumulative_net': cumulative if net is not None else None,
                           'cumulative_net_days': cumulative_days,
                           'hs300': baseline.get('hs300'), 'hs300_change_percent': baseline.get('hs300_change_percent'),
                           'peak_ratio': ratio, 'covered': baseline.get('covered', 0) if basket else sum(r.get('net') is not None for r in rows), 'expected': len(target),
                           'amount_snapshot_ids': payload.get('amount_snapshot_ids', []),
                           'snapshot_ids': list({v for v in [baseline.get('snapshot_id'), snapshot_id, *payload.get('amount_snapshot_ids', []), *payload.get('supplement_snapshot_ids', [])] if v is not None})})
        funds = []
        for fund_code, values in fund_values.items():
            rows = [row for _, row in values]
            funds.append({'code': fund_code, 'name': universe[fund_code]['name'], 'index': universe[fund_code]['index'],
                          'net': observed_sum([r.get('net') for r in rows]),
                          'amount': observed_sum([r.get('amount') for r in rows]),
                          'scale': rows[-1].get('scale') if rows else None,
                          'as_of': values[-1][0] if values else None, 'days': sum(r.get('net') is not None for r in rows),
                          'amount_days': sum(r.get('amount') is not None for r in rows), 'expected_days': len(days)})
        valid = [p for p in series if p['net'] is not None]
        # Totals cover observed trading days; missing observations remain explicit
        # for both the UI and analysis clients, rather than invalidating the interval.
        summary = {'aggregation': 'available_observations', 'net': observed_sum([p['net'] for p in series]),
                   'inflow': sum(max(p['net'], 0) for p in valid) if valid else None,
                   'outflow': sum(min(p['net'], 0) for p in valid) if valid else None,
                   'amount': observed_sum([p['amount'] for p in series]), 'days': len(days), 'net_days': len(valid),
                   'amount_days': sum(p['amount'] is not None for p in series),
                   'missing_net_dates': [p['date'] for p in series if p['net'] is None],
                   'missing_amount_dates': [p['date'] for p in series if p['amount'] is None],
                   'loaded_days': sum(day in daily for day in days), 'funds': len(target),
                   'coverage_min': min((p['covered'] for p in series), default=0),
                   'coverage_max': max((p['covered'] for p in series), default=0)}
        signals = [{'date': p['date'], 'net': p['net'], 'peak_ratio': p['peak_ratio'],
                    'hs300_change_percent': p['hs300_change_percent'], 'snapshot_ids': p['snapshot_ids'],
                    'actor': None, 'rule_version': 'countertrend-v1'} for p in series
                   if p['net'] is not None and p['net'] > 0 and (p['peak_ratio'] or 0) >= 2
                   and p['hs300_change_percent'] is not None and p['hs300_change_percent'] < 0]
        return {'range': {'start': start, 'end': end}, 'series': series, 'summary': summary,
                'funds': sorted(funds, key=lambda r: (r['net'] is None, -(r['net'] or 0), r['code'])),
                'universe': [{'code': c, 'name': r['name']} for c, r in universe.items()],
                'holdings_trend': report_points, 'disclosures': disclosures, 'signals': signals,
                'basket_composition': composition, 'basket_as_of': end if national else None,
                'composition_mode': 'period_end_disclosed' if national else 'broad_market',
                'flow_attribution': 'all_etf_investors', 'knowledge_cutoff': cutoff,
                'units': {'money': '100000000 CNY', 'holding_trend_shares': '100000000 units', 'disclosure_shares': 'units'}}
