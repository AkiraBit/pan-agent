import asyncio
import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select

from test_etf_dashboard import database, board, report
from src.modules.market.etf import free_sources as adapters, free_store as store, free_collector as collector, service, history, turnover
from src.modules.market.etf.models import EtfDaily, EtfFlowDay, EtfSnapshot, EtfMeasurement, EtfFetchState
from src.platform.persistence.models import DataSource


def sz_page(page=1, total=2, pages=2, date='2026-11-12', value='1,234.56'):
    return [{'metadata': {'pageno': page, 'recordcount': total, 'pagecount': pages,
                         'cols': {'current_size': '基金规模<br>(万份)'}},
             'data': [{'size_date': date, 'fund_code': '159915  ', 'current_size': value}]}]


@pytest.mark.parametrize('value', [None, True, 'NaN', 'Infinity', '1,23.4', '-2', '1e20'])
def test_reject_invalid_numeric_values(value):
    with pytest.raises(adapters.InvalidData):
        adapters.number(value, positive=True)


def test_nav_json_only_and_identity_and_conflict():
    points = [{'x': 1794499200000, 'y': 4.2, 'unitMoney': ''}]
    body = ('var fS_code="510300"; var Data_netWorthTrend=' + json.dumps(points) + ';throw new Error("must not execute")').encode()
    rows, raw = adapters.parse_nav(body, '510300', '2026-11-01', '2026-11-13')
    assert rows[0]['date'] == '2026-11-13' and rows[0]['nav'] == 4.2
    with pytest.raises(adapters.InvalidData, match='code'):
        adapters.parse_nav(body, '159915', '2026-11-01', '2026-11-13')
    with pytest.raises(adapters.InvalidData, match='duplicate'):
        adapters.unique([rows[0], {**rows[0], 'nav': 5}])


def test_prices_require_raw_ohlc_and_exact_range():
    payload = {'code': 0, 'data': {'sh510300': {'day': [['2026-11-13', '4', '4.1', '4.2', '3.9', '1200']]}}}
    assert adapters.parse_prices(payload, 'sh510300', '2026-11-13', '2026-11-13')[0]['close'] == 4.1
    with pytest.raises(adapters.InvalidData, match='date'):
        adapters.parse_prices(payload, 'sh510300', '2026-11-12', '2026-11-12')
    payload['data']['sh510300']['day'][0][3] = '3'
    with pytest.raises(adapters.InvalidData, match='ohlc'):
        adapters.parse_prices(payload, 'sh510300', '2026-11-13', '2026-11-13')


def put(resource, provider, rows, key=None):
    return store.save(adapters.Batch(resource, provider, rows, {'fixture': rows}, 'https://example.test/', {}),
                      key or f'{resource}:{provider}:test')


def missing(value):
    value = copy.deepcopy(value)
    value.update(net=None, covered=0)
    value['etfs'][0].update(net=None, shares_delta=None, scale=None)
    return value


def seed_inputs():
    put('price', 'tencent', [{'code': '510300', 'date': d, 'close': c} for d, c in [('2026-11-11', 4), ('2026-11-12', 4), ('2026-11-13', 4)]])
    put('shares', 'sse', [{'code': '510300', 'date': d, 'shares': n} for d, n in [('2026-11-11', 1e9), ('2026-11-12', 1.1e9), ('2026-11-13', 1.2e9)]])
    put('nav', 'eastmoney', [{'code': '510300', 'date': '2026-11-13', 'nav': 4.2}])


def test_backfill_versioning_primary_precedence_history_and_restart(database, board, monkeypatch):
    board = missing(board)
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-14T00:00:00+00:00')
    original = service.save_board(board, board)
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-15T00:00:00+00:00')
    seed_inputs(); store.rebuild()
    assert service.saved_board()['payload']['net'] == 4
    assert service.saved_board()['payload']['etfs'][0]['nav_cny'] == 4.2
    assert service.saved_board(knowledge_cutoff='2026-11-14T12:00:00+00:00')['payload']['net'] is None
    assert service.saved_board('2026-11-12')['payload']['source'] == 'public_sources'
    # Idempotent repeated collection and restarting retain exact observations.
    with database() as db:
        count = db.scalar(select(func.count()).select_from(EtfSnapshot))
        assert db.get(EtfSnapshot, original).payload['net'] is None
    seed_inputs(); store.rebuild(); service._checked.clear()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(EtfSnapshot)) == count
    service.save_board(board, board)
    with database() as db:
        assert db.get(EtfDaily, ('510300', '2026-11-13')).shares_delta == 1e8
    # Later board.series must not erase supplements on an earlier day.
    data = history.read_history('2026-11-12', '2026-11-13', ['2026-11-12', '2026-11-13'])
    assert data['summary']['net'] == 8 and data['summary']['coverage_min'] == 1
    with database() as db:
        assert db.get(EtfFlowDay, '2026-11-12').net_subscription_estimate_cny == 4e8
    assert all(p['snapshot_ids'] for p in data['series'])
    service.save_holdings([report('2025-12-31')])
    assert history.read_history('2026-11-12', '2026-11-13', [], national=True)['summary']['net'] == 8
    turnover.save([{'code': '510300', 'date': '2026-11-12', 'turnover_cny': 42, 'bar': {}}], {'2026-11-12'})
    assert service.saved_board('2026-11-12')['payload']['amount'] == 42 / 1e8
    # A primary correction wins without removing the independently recorded input.
    board.update(net=9, covered=1); board['etfs'][0]['net'] = 9
    service.save_board(board, board); store.rebuild()
    assert service.saved_board()['payload']['net'] == 9


def test_revision_reproducible_and_split_guard(database, board, monkeypatch):
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-15T00:00:00+00:00')
    board = missing(board); service.save_board(board, board); seed_inputs(); store.rebuild()
    old_time = service.timestamp()
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-16T00:00:00+00:00')
    put('shares', 'sse', [{'code': '510300', 'date': '2026-11-13', 'shares': 1.3e9}]); store.rebuild()
    assert service.saved_board()['payload']['net'] == 8
    assert service.saved_board(knowledge_cutoff=old_time)['payload']['net'] == 4
    put('nav', 'eastmoney', [{'code': '510300', 'date': '2026-11-13', 'nav': 4.2, 'corporate_action': '份额折算'}]); store.rebuild()
    assert service.saved_board()['payload']['net'] is None
    with database() as db:
        assert db.get(EtfDaily, ('510300', '2026-11-13')).net_subscription_estimate_cny is None
        assert store.derived(db)[('510300', '2026-11-13')].payload['quality'] == ['share_conversion_requires_review']


def test_partial_success_and_persistent_backoff(database):
    batch = adapters.Batch('shares', 'sse', [{'code': '510300', 'date': '2026-11-13', 'shares': 100}], {}, '', {})
    store.save(batch, 'partial', expected={('510300', '2026-11-13'), ('510500', '2026-11-13')})
    assert not store.due('partial')
    with database() as db:
        state = db.get(EtfFetchState, 'partial')
        assert state.status == 'error' and state.error == 'incomplete_expected_dates'
        assert db.scalar(select(func.count()).select_from(EtfMeasurement)) == 1
    store.save(batch, 'partial')
    with database() as db:
        assert db.get(EtfFetchState, 'partial').failures == 0
    with pytest.raises(adapters.InvalidData):
        store.save(adapters.Batch('shares', 'sse', [], {}, '', {}), 'empty')


@pytest.mark.anyio
async def test_disabled_sources_no_requests_and_resume_materialization(database, board, monkeypatch):
    service.save_board(missing(board), missing(board)); seed_inputs()
    fetch = AsyncMock(side_effect=AssertionError('disabled source requested'))
    monkeypatch.setattr(adapters, 'prices', fetch)
    assert await collector.collect() == 0
    with database() as db:
        db.add(DataSource(name='NAV', type='etf_nav', provider='eastmoney', enabled=True)); db.commit()
    monkeypatch.setattr(store, 'due', lambda key: False)
    # Simulates a process stopping after inputs committed but before rebuild.
    await collector.collect()
    assert service.saved_board()['payload']['net'] == 4
    fetch.assert_not_awaited()


@pytest.mark.anyio
async def test_transport_retries_throttle_and_live_disable(monkeypatch):
    sleep = AsyncMock(); monkeypatch.setattr(adapters.asyncio, 'sleep', sleep)
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(429 if len(seen) == 1 else 200, content=b'{"ok":true}')
    client = adapters.Client()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await client.json('https://example.test') == {'ok': True}
    assert len(seen) == 2
    await client.client.aclose()
    client.allowed = lambda: False
    with pytest.raises(adapters.Disabled):
        await client.get('https://example.test')


def test_retired_exchange_jobs_are_not_registered(database):
    from server import DATA_SOURCE_SEEDS
    pairs = {(s['type'], s['provider']) for s in DATA_SOURCE_SEEDS}
    assert (set(adapters.SPECS) - {("etf_nav", "fuyao")}) <= pairs
    assert ("fuyao:get_fund_performance_nav", "fuyao") in pairs
    assert not ({"etf_shares", "etf_pcf"} & {kind for kind, _ in pairs})
    with database() as db:
        db.add(DataSource(name="Legacy shares", type="etf_shares", provider="sse", enabled=True))
        db.commit()
    assert not store.enabled("etf_shares", "sse")
    assert store.settings() == []


def test_shares_can_fill_from_primary_prices_without_tencent(database, board):
    previous = copy.deepcopy(board); previous['date'] = '2026-11-12'; previous['series'] = []
    service.save_board(previous, previous)
    value = missing(board); service.save_board(value, value)
    put('shares', 'sse', [{'code': '510300', 'date': d, 'shares': n} for d, n in [('2026-11-12', 1e9), ('2026-11-13', 1.1e9)]])
    store.rebuild()
    assert service.saved_board()['payload']['net'] == 4


def test_daily_signals_follow_corrected_net(database, board):
    value = missing(board); value['peak_window'] = {'ratio': 3}
    service.save_board(value, value); seed_inputs(); store.rebuild()
    saved = service.saved_board()['payload']
    signals = service.national_team(saved)['signals']
    signal = next(r for r in signals if r['date'] == value['date'])
    assert signal['net_subscription_estimate_cny'] == 4e8 and signal['snapshot_ids']


def test_older_custom_range_survives_collection_restart(database, board):
    snap = service.save_board(board, board)
    with database() as db:
        db.add(EtfDaily(code='510300', trade_date='2025-01-02', name='ETF', index_name='沪深300', close=4, snapshot_id=snap))
        db.commit()
    assert store.context()['start'] == '2025-01-02'
