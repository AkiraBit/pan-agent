"""Durable public inputs and reproducible supplements, never rewritten board data."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from src.platform.persistence.models import DataSource
from . import free_sources, service, sources
from .models import EtfDaily, EtfFetchState, EtfFlowDay, EtfMeasurement, EtfSnapshot, EtfTurnover

FIELDS = {'close': 'close', 'change_percent': 'change_percent', 'shares_delta': 'shares_delta',
          'net_subscription_estimate_cny': 'net', 'scale_cny': 'scale'}
MONEY_FIELDS = {'shares_delta', 'net_subscription_estimate_cny', 'scale_cny'}
METHOD = 'shares_change_x_unadjusted_close-v1'


def enabled(kind, provider):
    with service.SessionLocal() as db:
        return db.scalar(select(DataSource.id).where(DataSource.type == kind, DataSource.provider == provider,
                                                     DataSource.enabled.is_(True)).limit(1)) is not None


def settings():
    with service.SessionLocal() as db:
        rows = db.scalars(select(DataSource).order_by(DataSource.priority, DataSource.id)).all()
        return [(r.type, r.provider) for r in rows if r.enabled and (r.type, r.provider) in free_sources.SPECS]


def context():
    with service.SessionLocal() as db:
        board = db.scalar(select(EtfSnapshot).where(EtfSnapshot.resource == 'board').order_by(EtfSnapshot.key.desc(), EtfSnapshot.id.desc()))
        if not board:
            return None
        first = db.scalar(select(func.min(EtfSnapshot.key)).where(EtfSnapshot.resource == 'board'))
        end = board.key
        stored_first = db.scalar(select(func.min(EtfDaily.trade_date)))
        # Custom historical ranges remain in the background queue after restart.
        start = min(first, stored_first or first, (date.fromisoformat(end) - timedelta(days=365)).isoformat())
        return {'universe': {r['code']: r for r in board.payload['etfs']}, 'start': start, 'end': end}


def due(key):
    with service.SessionLocal() as db:
        row = db.get(EtfFetchState, key)
        return row is None or row.retry_after <= service.timestamp()


def record_state(db, key, resource, provider, count=0, error=None, ttl=86400):
    old = db.get(EtfFetchState, key)
    failures = (old.failures if old else 0) + 1 if error else 0
    delay = min(21600, 60 * 2 ** min(failures, 8)) if error else ttl
    now = datetime.fromisoformat(service.timestamp())
    service.upsert(db, EtfFetchState, [{'key': key, 'resource': resource, 'source': provider,
        'status': 'error' if error else 'ok', 'checked_at': now.isoformat(),
        'retry_after': (now + timedelta(seconds=delay)).isoformat(), 'failures': failures,
        'error': error, 'record_count': count}], ['key'])


def failure(key, resource, provider, exc):
    import httpx
    if isinstance(exc, free_sources.InvalidData):
        message = str(exc)[:100]
    elif isinstance(exc, httpx.HTTPStatusError):
        message = f'http_{exc.response.status_code}'
    elif isinstance(exc, httpx.HTTPError):
        message = 'network_unavailable'
    else:
        message = 'invalid_provider_response'
    with service.SessionLocal() as db:
        record_state(db, key, resource, provider, error=message)
        db.commit()


def save(batch, key, *, expected=None, ttl=86400):
    if not batch.rows:
        raise free_sources.InvalidData('empty_observations')
    actual = {(r['code'], r['date']) for r in batch.rows}
    missing = (expected or set()) - actual
    with service.SessionLocal() as db:
        payload = {'rows': batch.rows, 'raw': batch.raw, 'request': batch.request,
                   'parser_version': free_sources.PARSER_VERSION, 'units': {'money': 'CNY', 'shares': 'units'}}
        snap = service.snapshot(db, batch.resource, key, payload, batch.source, batch.url)
        previous = {(r.code, r.trade_date): r.payload for r in db.scalars(select(EtfMeasurement).where(
            EtfMeasurement.resource == batch.resource, EtfMeasurement.source == batch.source))}
        service.upsert(db, EtfMeasurement, [{'resource': batch.resource, 'source': batch.source,
            'code': r['code'], 'trade_date': r['date'], 'payload': r, 'snapshot_id': snap.id} for r in batch.rows if previous.get((r['code'], r['date'])) != r],
            ['resource', 'source', 'code', 'trade_date'])
        record_state(db, key, batch.resource, batch.source, len(batch.rows),
                     error='incomplete_expected_dates' if missing else None, ttl=ttl)
        db.commit()
    return len(batch.rows)


def derived(db, cutoff=None):
    query = select(func.max(EtfSnapshot.id)).where(EtfSnapshot.resource == 'derived')
    if cutoff:
        query = query.where(EtfSnapshot.observed_at <= cutoff)
    rows = db.scalars(select(EtfSnapshot).where(EtfSnapshot.id.in_(query.group_by(EtfSnapshot.key)))).all()
    return {(r.payload['code'], r.payload['date']): r for r in rows}


def original_row(db, daily):
    if daily is None:
        return {}
    snap = db.get(EtfSnapshot, daily.snapshot_id)
    if not snap or snap.resource != 'board':
        return {}
    return next((r for r in sources.validate_board(snap.payload)['etfs'] if r['code'] == daily.code), {})


def rebuild(start=None):
    ctx = context()
    if not ctx:
        return 0
    with service.SessionLocal() as db:
        inputs = db.scalars(select(EtfMeasurement)).all()
        by = {(r.resource, r.source, r.code, r.trade_date): r for r in inputs}
        prices = {}
        for row in inputs:
            if row.resource == 'price':
                prices.setdefault(row.code, {})[row.trade_date] = row
        daily = {(r.code, r.trade_date): r for r in db.scalars(select(EtfDaily))}
        board_ids = {r.snapshot_id for r in daily.values()}
        originals = {}
        for s in db.scalars(select(EtfSnapshot).where(EtfSnapshot.id.in_(board_ids), EtfSnapshot.resource == 'board')):
            for r in sources.validate_board(s.payload)['etfs']:
                originals[(s.id, r['code'])] = r
        # A separately disabled quote source must not block exchange share inputs
        # when the original board already provides an unadjusted closing price.
        for (code, d), row in daily.items():
            original = originals.get((row.snapshot_id, code), {})
            if original.get('close') is not None:
                prices.setdefault(code, {}).setdefault(d, SimpleNamespace(payload={'close': original['close']},
                    snapshot_id=row.snapshot_id, trade_date=d))
        saved_derivations = derived(db)
        # Primary NAV wins; PCF is dated by PreTradingDay, never by publication day.
        navs = {}
        for row in sorted(inputs, key=lambda r: (r.resource == 'nav', r.snapshot_id)):
            if row.resource in {'nav', 'pcf'}:
                navs[(row.code, row.payload.get('nav_date', row.trade_date))] = row
        changed, affected = 0, set()
        for code, points in prices.items():
            if code not in ctx['universe'] and code != '000300':
                continue
            ordered = sorted(points)
            for i, d in enumerate(ordered):
                if d < (start or ctx['start']):
                    continue
                price = points[d]
                prev = points[ordered[i - 1]] if i else None
                current = daily.get((code, d))
                original = originals.get((current.snapshot_id, code), {}) if current else {}
                close = original.get('close') or price.payload['close']
                value = {'close': close, 'change_percent': (close / prev.payload['close'] - 1) * 100 if prev else None,
                         'shares_delta': None, 'net_subscription_estimate_cny': None, 'scale_cny': None}
                ids = {price.snapshot_id}
                if original.get('close') is not None:
                    ids.add(current.snapshot_id)
                if prev:
                    ids.add(prev.snapshot_id)
                source = 'szse' if code.startswith('15') else 'sse'
                share = by.get(('shares', source, code, d))
                previous = by.get(('shares', source, code, prev.trade_date)) if prev else None
                nav = navs.get((code, d))
                quality = []
                if nav:
                    value['nav_cny'] = nav.payload['nav']
                    ids.add(nav.snapshot_id)
                if share:
                    units = share.payload['shares']
                    value.update(shares_total=units, scale_cny=round(units * close, 2))
                    ids.add(share.snapshot_id)
                    if nav:
                        value['nav_scale_cny'] = round(units * nav.payload['nav'], 2)
                    if previous and prev:
                        ids.add(previous.snapshot_id)
                        sr = units / previous.payload['shares']
                        pr = close / prev.payload['close']
                        action = nav.payload.get('corporate_action', '') if nav else ''
                        if ('拆分' in action or '折算' in action or
                            ((sr > 1.5 or sr < .67) and abs(pr - 1) > .3 and abs(sr * pr - 1) < .15)):
                            quality.append('share_conversion_requires_review')
                        else:
                            delta = round(units - previous.payload['shares'], 2)
                            value.update(shares_delta=delta, net_subscription_estimate_cny=round(delta * close, 2))
                            if nav:
                                value['net_at_nav_estimate_cny'] = round(delta * nav.payload['nav'], 2)
                record = {'code': code, 'date': d, 'values': value, 'method': METHOD,
                          'quality': quality, 'input_snapshot_ids': sorted(ids)}
                snap = saved_derivations.get((code, d))
                if not snap or snap.payload != record:
                    snap = service.snapshot(db, 'derived', f'{code}:{d}', record, 'panwatch', '/api/etf/observations?resource=derived')
                if code == '000300':
                    continue
                if current is None:
                    identity = ctx['universe'][code]
                    current = EtfDaily(code=code, trade_date=d, name=identity['name'], index_name=identity['index'], snapshot_id=snap.id)
                    db.add(current); daily[(code, d)] = current
                elif not original:
                    current.snapshot_id = snap.id
                for field, board_field in FIELDS.items():
                    base = original.get(board_field)
                    result = base * 1e8 if base is not None and field in MONEY_FIELDS else base
                    result = value.get(field) if result is None else result
                    if getattr(current, field) != result:
                        setattr(current, field, result); changed += 1
                affected.add(d)
        db.flush()
        index = prices.get('000300', {})
        for d in affected:
            members = [r for (c, day), r in daily.items() if day == d and c in ctx['universe']]
            known = [r.net_subscription_estimate_cny for r in members if r.net_subscription_estimate_cny is not None]
            flow = db.get(EtfFlowDay, d)
            if not flow:
                flow = EtfFlowDay(trade_date=d, snapshot_id=members[0].snapshot_id, covered=0)
                db.add(flow)
            flow.covered = len(known)
            flow.net_subscription_estimate_cny = sum(known) if known else None
            if d in index and flow.index_close is None:
                flow.index_close = index[d].payload['close']
        db.commit()
    return changed


def overlay(payload, supplements):
    rows, evidence, filled_net = [], [], False
    for original in payload['etfs']:
        row = dict(original)
        saved = supplements.get((row['code'], payload['date']))
        if saved:
            values = saved.payload['values']
            used = False
            for field, target in FIELDS.items():
                if row.get(target) is None and values.get(field) is not None:
                    row[target] = values[field] / 1e8 if field in MONEY_FIELDS else values[field]
                    used = True
                    filled_net |= target == 'net'
            for field in ('shares_total', 'nav_cny', 'nav_scale_cny', 'net_at_nav_estimate_cny'):
                if field in values:
                    row[field] = values[field]
                    used = True
            if used:
                evidence.extend([saved.id, *saved.payload['input_snapshot_ids']])
                row['supplement_snapshot_id'] = saved.id
                row['estimation_method'] = saved.payload['method']
        rows.append(row)
    result = {**payload, 'etfs': rows, 'supplement_snapshot_ids': sorted(set(evidence))}
    if filled_net or payload.get('source') == 'public_sources':
        known = [r['net'] for r in rows if r.get('net') is not None]
        result.update(net=sum(known) if known else None, covered=len(known),
                      shares_published=bool(known), shares_final=len(known) == len(rows),
                      net_source=METHOD)
    if rows and all(r.get('scale') is not None for r in rows):
        result['scale'] = sum(r['scale'] for r in rows)
    point = supplements.get(('000300', payload['date']))
    if point:
        if result.get('hs300') is None or result.get('hs300_change_percent') is None:
            result['supplement_snapshot_ids'] = sorted(set(result['supplement_snapshot_ids'] + [point.id, *point.payload['input_snapshot_ids']]))
        result['hs300'] = result.get('hs300') or point.payload['values']['close']
        if result.get('hs300_change_percent') is None:
            result['hs300_change_percent'] = point.payload['values'].get('change_percent')
    return result


def synthetic(day, universe, supplements):
    available = [r for (c, d), r in supplements.items() if d == day and c in universe and r.payload['values'].get('close') is not None]
    if not available:
        return None
    base = {'date': day, 'status': '收盘', 'source': 'public_sources', 'covered': 0, 'net': None,
            'amount': None, 'scale': None, 'net20': None, 'shares_published': False, 'shares_final': False,
            'updated_at': max(r.observed_at for r in available), 'minutes': [], 'profile': [],
            'cumulative': [], 'windows': [], 'series': [], 'surges': [], 'peak_window': None,
            'hs300_change_percent': None, 'signal': {'kind': 'normal', 'title': '', 'detail': ''},
            'etfs': [{**r, **{k: None for k in ('close', 'change_percent', 'amount', 'net', 'net20', 'shares_delta', 'scale', 'peak_window')}}
                     for r in universe.values()]}
    return overlay(base, supplements)


def saved_dates(db, cutoff=None):
    return sorted({d for (c, d), snap in derived(db, cutoff).items() if c != '000300' and snap.payload['values'].get('close') is not None})
