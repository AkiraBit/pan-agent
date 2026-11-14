from datetime import datetime, timedelta
import json
import zlib

import pytest
from marketdata import short_term as source
from marketdata.short_term import Batch, TZ
from src.modules.short_term.analysis import analyze, phase_at, reference_day

NOW = datetime(2026, 11, 11, 9, 40, tzinfo=TZ)
DAY = '2026-11-11'


def row(code='600000', change=4, timestamp=None):
    return {'code': code, 'name': code, 'change': change,
            'source_time': NOW.timestamp() if timestamp is None else timestamp, 'streak': 2}


def batch(scope='market', rows=None):
    rows = [row(str(n)) for n in range(5)] if rows is None else rows
    return Batch(scope, rows, len(rows), 'complete', 'ok', trade_date=DAY)


def inputs():
    return [batch(), batch('concepts'), [(row('BK001'), batch('theme'))],
            {k: batch(k, []) for k in source.POOLS}]


@pytest.mark.parametrize('clock,expected', [
    ('09:14:59', 'premarket'), ('09:15:00', 'auction_early'),
    ('09:20:00', 'auction_late'), ('09:25:00', 'auction_result'),
    ('09:30:00', 'opening'), ('10:00:00', 'trading'),
    ('11:30:00', 'break'), ('13:00:00', 'trading'), ('15:00:00', 'review')])
def test_exchange_phase_boundaries(clock, expected):
    assert phase_at(datetime.fromisoformat(f'{DAY}T{clock}+08:00')) == expected


def test_calendar_reference_and_execution_unchanged():
    from src.platform.scheduling.trading_calendar import market_status
    monday = datetime(2026, 11, 9, 9, 20, tzinfo=TZ)
    assert reference_day(monday) == '2026-11-06'
    assert market_status('CN', monday) == 'pre_market'
    assert phase_at(datetime(2035, 1, 2, 10, tzinfo=TZ)) == 'unknown'
    assert phase_at(datetime(2026, 11, 14, 10, tzinfo=TZ)) == 'closed'


def test_full_market_and_theme_evidence():
    args = inputs()
    args[3]['up'] = batch('up', [row()])
    args[3]['broken'] = batch('broken', [row('600001')])
    args[3]['yesterday'] = batch('yesterday', [row(change=4), row('600001', -2)])
    result = analyze(*args, NOW, DAY)
    assert result['environment'] == 'broad_strength'
    assert result['themes'][0]['state'] == 'synchronized'
    assert result['sentiment']['break_rate'] == .5
    assert result['sentiment']['yesterday_mean'] == 1
    assert result['auction']['available'] is False
    assert result['captured_at'].endswith('+00:00')


@pytest.mark.parametrize('fault', ['partial', 'stale', 'unknown_time', 'old', 'future', 'invalid_changes', 'auction'])
def test_missing_or_old_data_never_produces_live_verdict(fault):
    args = inputs()
    market = args[0]
    now = NOW
    if fault == 'partial':
        market.status = 'partial'
    elif fault == 'invalid_changes':
        market.rows[0]['change'] = None
    elif fault == 'auction':
        now = NOW.replace(hour=9, minute=22)
    else:
        stamp = {'stale': (NOW - timedelta(days=1)).timestamp(), 'old': NOW.timestamp() - 181,
                 'future': NOW.timestamp() + 31, 'unknown_time': None}[fault]
        for r in market.rows:
            r['source_time'] = stamp
    result = analyze(*args, now, DAY)
    assert result['environment'] == 'pending'
    assert result['themes'][0]['state'] == 'pending'


def test_lone_leader_is_not_theme_strength_and_missing_pool_is_not_zero():
    args = inputs()
    args[2][0][1].rows = [row('0', 10), row('1', -1), row('2', -2), row('3', -1), row('4', 0)]
    args[3]['broken'] = Batch('broken')
    result = analyze(*args, NOW, DAY)
    assert result['themes'][0]['state'] == 'divergent'
    assert result['sentiment']['counts']['down'] == 0
    assert result['sentiment']['counts']['broken'] is None
    assert result['sentiment']['break_rate'] is None
    assert result['sentiment']['yesterday_mean'] is None


def test_old_concept_ranking_cannot_claim_theme_strength():
    args = inputs()
    for r in args[1].rows:
        r['source_time'] = None
    assert analyze(*args, NOW, DAY)['themes'][0]['state'] == 'pending'


def raw_row(n):
    return {'f12': str(n), 'f14': f'Stock {n}', 'f2': 10, 'f3': '-', 'f6': 10000, 'f5': 100, 'f124': NOW.timestamp()}


@pytest.mark.parametrize('fault', ['none', 'missing', 'duplicate', 'changing_total', 'invalid'])
def test_full_pagination_integrity(monkeypatch, fault):
    def page(fs, n):
        if n == 1:
            return 201, [raw_row(i) for i in range(100)]
        if n == 2:
            return 201, [raw_row(i) for i in range(100, 200)]
        if fault == 'missing':
            return None
        if fault == 'invalid':
            return 201, [{}]
        return (202 if fault == 'changing_total' else 201), [raw_row(1 if fault == 'duplicate' else 200)]
    monkeypatch.setattr(source, '_page', page)
    result = source.quotes()
    assert result.status == ('complete' if fault == 'none' else 'partial')
    assert result.expected == 201
    assert result.rows[0]['change'] is None
    assert result.rows[0]['volume'] == 100
    assert result.rows[0]['amount'] == 10000


def test_diff_dictionary_and_failure_contract(monkeypatch):
    monkeypatch.setattr(source, '_get', lambda *a: {'rc': 0, 'data': {'total': 1, 'diff': {'0': raw_row(1)}}})
    assert source.quotes().status == 'complete'
    monkeypatch.setattr(source, '_get', lambda *a: {'rc': 1, 'data': {'total': 0, 'diff': []}})
    assert source.quotes().status == 'unavailable'


@pytest.mark.parametrize('kind', list(source.POOLS))
def test_limit_pools_valid_empty_and_nonempty(monkeypatch, kind):
    payload = {'rc': 0, 'data': {'qdate': 20261111, 'tc': 0, 'pool': []}}
    monkeypatch.setattr(source, '_get', lambda *a: payload)
    assert source.limit_pool(kind, DAY).status == 'complete'
    payload['data'].update(tc=1, pool=[{'c': '600001', 'n': 'Example', 'zdp': -10, 'lbc': 2}])
    assert source.limit_pool(kind, DAY).rows[0]['change'] == -10
    payload['data']['qdate'] = 20261110
    assert source.limit_pool(kind, DAY).reason == 'date_mismatch'
    payload['data'] = None
    assert source.limit_pool(kind, DAY).status == 'unavailable'


def test_nonfinite_numbers():
    assert source.number(float('nan')) is None
    assert source.number('Infinity') is None
    assert source.number(0) == 0


def test_collection_persists_immutable_evidence(monkeypatch):
    from src.modules.short_term import api
    from src.platform.persistence.models import ShortTermSnapshot
    from src.platform.persistence.database import SessionLocal
    monkeypatch.setattr(api, 'quotes', lambda *a: batch())
    monkeypatch.setattr(api, 'limit_pool', lambda *a: batch('pool', []))
    monkeypatch.setattr(api, 'reference_day', lambda *a: DAY)
    monkeypatch.setattr(api, 'phase_at', lambda *a: 'review')
    api.collect()
    with SessionLocal() as db:
        first = db.query(ShortTermSnapshot).order_by(ShortTermSnapshot.id.desc()).first()
        first_id, saved = first.id, json.dumps(first.payload)
        assert zlib.decompress(first.evidence)
    api.collect()
    with SessionLocal() as db:
        assert json.dumps(db.get(ShortTermSnapshot, first_id).payload) == saved
    assert api.overview(first_id)['snapshot']['id'] == first_id
    assert api.overview(None)['snapshot']['id'] > first_id


def test_refresh_single_flight_and_cooldown(monkeypatch):
    from concurrent.futures import Future
    from src.modules.short_term import api
    future = Future()
    monkeypatch.setattr(api, '_future', future)
    monkeypatch.setattr(api, '_started', api.time.monotonic())
    assert api.refresh() == {'state': 'collecting'}
    future.set_result(None)
    assert api.refresh()['state'] == 'cooldown'


def test_theme_excludes_other_exchanges():
    args = inputs()
    args[2][0][1].rows.append(row('920001', 30))
    args[2][0][1].expected += 1
    theme = analyze(*args, NOW, DAY)['themes'][0]
    assert theme['breadth']['valid'] == 5
    assert all(r['code'] != '920001' for r in theme['leaders'])


def test_yesterday_pool_uses_its_supported_sort(monkeypatch):
    def get(url, params):
        assert params['sort'] == 'zs:desc'
        return {'rc': 0, 'data': {'qdate': 20261111, 'tc': 0, 'pool': []}}
    monkeypatch.setattr(source, '_get', get)
    assert source.limit_pool('yesterday', DAY).status == 'complete'
