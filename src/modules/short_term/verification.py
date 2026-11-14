"""Deterministic, source-timed observation of Agent-authored numeric rules."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from marketdata.short_term import TZ
from src.platform.scheduling.trading_calendar import calendar_known, is_trading_day

WINDOWS = {'premarket': (time(8), time(9, 15)), 'auction': (time(9, 15), time(9, 30)),
           'opening': (time(9, 30), time(10)), 'afternoon': (time(13), time(14, 57)),
           'close': (time(14, 57), time(15, 5)), 'next_session': (time(9, 30), time(10))}


def next_session(day):
    cursor = datetime.fromisoformat(day).date()
    for _ in range(32):
        cursor += timedelta(days=1)
        if not calendar_known('CN', cursor):
            return None
        if is_trading_day('CN', cursor):
            return cursor.isoformat()
    return None


def sample_phase(now):
    local = now.astimezone(TZ)
    if not calendar_known('CN', local) or not is_trading_day('CN', local):
        return 'closed'
    clock = local.time()
    if time(9, 15) <= clock < time(9, 30): return 'auction'
    if time(9, 30) <= clock <= time(11, 30): return 'continuous'
    if time(13) <= clock < time(14, 57): return 'continuous'
    if time(14, 57) <= clock <= time(15, 5): return 'close'
    return 'closed'


def metric(check, sample, now):
    auction_metric = check['metric'] in {'auction_change_pct', 'matched_amount_cny', 'unmatched_ratio'}
    rows = sample['auction'].get('quotes', []) if auction_metric else sample['quotes']
    quote = next((q for q in rows if q['symbol'] == check['symbol']), None)
    if not quote or not quote.get('source_time'):
        return None, None, 'source_missing'
    stamp = datetime.fromisoformat(quote['source_time'])
    if stamp.tzinfo is None or stamp.astimezone(TZ).date() != now.astimezone(TZ).date():
        return None, None, 'quote_wrong_date'
    age = (now-stamp).total_seconds()
    tolerance = 300 if auction_metric and quote.get('final') else 15 if auction_metric else 90
    # An official closing snapshot remains a closing observation until 15:05.
    if not auction_metric and now.astimezone(TZ).time() >= time(15) and stamp.astimezone(TZ).time() >= time(15):
        tolerance = 300
    if not 0 <= age <= tolerance:
        return None, None, 'quote_not_fresh'
    if check['metric'] == 'open_change_pct':
        value = (quote['price']/quote['open']-1)*100 if quote.get('open') and quote.get('price') else None
    else:
        value = quote.get(check['metric'])
    return value, quote['source_time'], None if value is not None else 'metric_missing'


def evaluate_conditions(publication, sample, previous=None, *, max_gap_seconds=90):
    now = datetime.fromisoformat(sample['observed_at']).astimezone(TZ)
    previous = {r['id']: r for r in (previous or [])}
    result = []
    for condition in publication['analysis']['conditions']:
        identity = condition['id']
        prior = previous.get(identity, {})
        target = next_session(publication['target_trade_date']) if condition['window']=='next_session' else publication['target_trade_date']
        start, end = WINDOWS[condition['window']]
        row = {'id': identity, 'state': 'waiting', 'reason': 'window_not_reached',
               'observed_at': sample['observed_at'], 'observed_value': None, 'checks': [],
               'since': None, 'last_source_time': None, 'observations': 0, 'evidence_ids': [sample['id']]}
        if prior.get('state') == 'invalidated':
            result.append({**prior, 'window_closed': now.date().isoformat() > (target or '') or now.time() > end})
            continue
        day = now.date().isoformat()
        if not target or day < target or (day == target and now.time() < start):
            result.append(row); continue
        if day > target or now.time() > end:
            if prior.get('last_source_time'):
                row = {**prior, 'window_closed': True}
            else:
                row.update(state='unknown', reason='window_not_sampled', window_closed=True)
            result.append(row); continue
        rule = condition.get('rule')
        if not rule and condition.get('expression'):
            rule = {'checks': [condition['expression']], 'mode': 'all', 'persistence_seconds': 0, 'invalidation_checks': []}
        if not rule:
            row.update(state='review_required', reason='qualitative_condition')
            result.append(row); continue
        checks, stamps = [], []
        for check in [*rule['checks'], *rule.get('invalidation_checks', [])]:
            value, stamp, error = metric(check, sample, now)
            # Regular quote timestamps during auction do not turn last trade
            # prices or turnover into indicative matching observations.
            if condition['window'] == 'auction' and check['metric'] not in {'auction_change_pct', 'matched_amount_cny', 'unmatched_ratio'}:
                value, stamp, error = None, None, 'metric_missing'
            if stamp and not start <= datetime.fromisoformat(stamp).astimezone(TZ).time() <= end:
                error = 'source_outside_window'
            checks.append({**check, 'observed_value': value, 'source_time': stamp, 'error': error,
                           'passed': None if error else value >= check['value'] if check['operator']=='gte' else value <= check['value']})
            if stamp: stamps.append(stamp)
        row['checks'] = checks
        if any(c['error'] for c in checks):
            row.update(state='unknown', reason=next(c['error'] for c in checks if c['error']))
            result.append(row); continue
        stamp = min(stamps, key=datetime.fromisoformat)
        # Repeated HTTP reads of the same source timestamp never build persistence.
        if prior.get('last_source_time') and datetime.fromisoformat(stamp) <= datetime.fromisoformat(prior['last_source_time']):
            row = {**prior, 'reason': 'duplicate_source_sample'}
            result.append(row); continue
        base = checks[:len(rule['checks'])]
        passed = all(c['passed'] for c in base) if rule.get('mode','all')=='all' else any(c['passed'] for c in base)
        invalidated = any(c['passed'] for c in checks[len(base):])
        row.update(last_source_time=stamp, observations=1, observed_value=base[0]['observed_value'])
        if invalidated:
            row.update(state='invalidated', reason='invalidation_observed')
        elif not passed:
            row.update(state='not_met', reason='sample_comparison')
        else:
            previous_stamp = prior.get('last_source_time')
            continuous = previous_stamp and prior.get('since') and 0 < (datetime.fromisoformat(stamp)-datetime.fromisoformat(previous_stamp)).total_seconds() <= max_gap_seconds
            since = prior['since'] if continuous else stamp
            seconds = (datetime.fromisoformat(stamp)-datetime.fromisoformat(since)).total_seconds()
            row.update(since=since, observations=prior.get('observations',0)+1 if continuous else 1,
                       state='met' if seconds >= rule.get('persistence_seconds',0) else 'observing',
                       reason='sustained_comparison' if rule.get('persistence_seconds',0) else 'sample_comparison')
        result.append(row)
    return result
