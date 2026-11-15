import asyncio
import copy
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from src.platform.persistence.database import Base
from src.modules.market.etf import service, sources
from src.modules.market.etf.models import EtfDaily, EtfFlowDay, EtfHolding, EtfMinute, EtfSnapshot
from src.modules.market.api import etf as api
from src.modules.administration.api.auth import get_current_user


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/etf.db', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(service, 'SessionLocal', factory)
    monkeypatch.setattr(api, 'SessionLocal', factory)
    service._checked.clear(); service._retry.clear(); service._inflight.clear()
    monkeypatch.setattr(service, '_holders_checked', 0)
    yield factory
    engine.dispose()


@pytest.fixture
def board():
    return {'date': '2026-11-13', 'status': '收盘', 'covered': 1, 'shares_published': True,
            'amount': 10, 'net': 4, 'net20': 15, 'updated_at': '2026-11-14T08:00:00+08:00',
            'etfs': [{'code': '510300', 'name': '沪深300ETF', 'index': '沪深300', 'manager': '华泰柏瑞',
                      'close': 4, 'net': 4, 'amount': 10, 'shares_delta': 1, 'scale': 400, 'peak_window': {'ratio': 3}}],
            'minutes': [['09:31', 2], ['09:32', 8]], 'profile': [['09:31', 1], ['09:32', 4]],
            'series': [{'date': '2026-11-12', 'covered': 1, 'net': -2, 'hs300_change_percent': -1}],
            'hs300_change_percent': -1, 'peak_window': {'ratio': 3}}


def report(period, shares=100, name='中央汇金投资有限责任公司'):
    return {'code': '510300', 'report_date': period, 'holders': [{'holder_name': name, 'shares': shares,
            'ratio_percent': 25, 'institution': sources.INSTITUTIONS.get(name)}], 'raw': {'shares': shares}}


def test_persistence_units_idempotency_revisions_and_snapshot_reversion(database, board):
    first = service.save_board(board, board)
    assert service.save_board(board, board) == first
    with database() as db:
        quote = db.get(EtfDaily, ('510300', '2026-11-13'))
        assert quote.shares_delta == 100_000_000
        assert quote.net_subscription_estimate_cny == 400_000_000
        assert db.scalar(select(func.count()).select_from(EtfMinute)) == 2
        assert db.get(EtfFlowDay, '2026-11-12').net_subscription_estimate_cny == -200_000_000
    revised = {**board, 'net': 5}
    second = service.save_board(revised, revised)
    assert second != first and service.saved_board()['payload']['net'] == 5
    third = service.save_board(board, board)
    assert third != first and service.saved_board()['payload']['net'] == 4
    with database() as db:
        assert db.get(EtfSnapshot, first).payload['net'] == 4
        assert db.get(EtfSnapshot, second).payload['net'] == 5


@pytest.mark.anyio
async def test_cold_concurrent_reads_fetch_once_and_survive_upstream_failure(database, board, monkeypatch):
    async def fetch(requested):
        await asyncio.sleep(.03)
        return board, board
    upstream = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(sources, 'board', upstream)
    results = await asyncio.gather(*(service.board() for _ in range(6)))
    assert upstream.await_count == 1
    assert all(r['payload']['date'] == '2026-11-13' for r in results)
    service._checked.clear()  # a restarted process has no memory cache
    monkeypatch.setattr(sources, 'board', AsyncMock(side_effect=httpx.ConnectError('offline')))
    restored = await service.board()
    assert restored['stale'] and restored['snapshot_id'] == results[0]['snapshot_id']
    with pytest.raises(httpx.ConnectError):
        await service.board('2026-11-12')  # never substitute another trading day


@pytest.mark.parametrize('mutation', ['wrong_date', 'duplicates', 'coverage', 'negative_turnover', 'nan', 'future_history', 'unordered_minutes'])
def test_invalid_source_data_is_rejected(board, mutation):
    value = copy.deepcopy(board)
    if mutation == 'wrong_date': value['date'] = '2026-11-12'
    if mutation == 'duplicates': value['etfs'] *= 2; value['covered'] = 2
    if mutation == 'coverage': value['covered'] = 2
    if mutation == 'negative_turnover': value['etfs'][0]['amount'] = -1
    if mutation == 'nan': value['etfs'][0]['net'] = float('nan')
    if mutation == 'future_history': value['series'][0]['date'] = '2026-11-14'
    if mutation == 'unordered_minutes': value['minutes'].reverse()
    with pytest.raises(ValueError):
        sources.validate_board(value, '2026-11-13')


def test_unpublished_shares_remain_null_and_do_not_emit_buy_signals(database, board):
    raw = {**board, 'shares_published': False}
    normalized = sources.validate_board(raw)
    service.save_board(normalized, raw)
    with database() as db:
        assert db.get(EtfDaily, ('510300', board['date'])).net_subscription_estimate_cny is None
        assert db.get(EtfDaily, ('510300', board['date'])).shares_delta is None
    assert service.national_team(normalized)['signals'] == []


def test_holder_periods_identity_cutoff_and_missing_do_not_imply_zero(database, board):
    service.save_board(board, board)
    service.save_holdings([report('2025-06-30', 80), report('2025-12-31', 100)])
    data = service.national_team(board)
    assert data['holdings'][0]['shares_change'] == 20
    assert data['holdings'][0]['announced_at'] is None
    assert data['holdings'][0]['report_date'] == '2025-12-31'
    assert data['watchlist_net_estimate_cny'] == 400_000_000
    assert data['flow_attribution'] == 'all_etf_investors'
    assert data['signals'][0]['actor'] is None
    assert service.national_team(board, '2026-01-01T00:00:00+00:00')['holdings'] == []
    service.save_holdings([report('2026-06-30', 100, '其他机构')])
    assert service.national_team(board)['holdings'] == []  # no invented liquidation
    service.save_holdings([report('2026-12-31', 500)])
    assert service.national_team(board)['holdings'] == []  # no future reporting period


def test_new_holder_has_unknown_prior_change(database, board):
    service.save_holdings([report('2025-06-30', 80, '其他机构'), report('2025-12-31', 100)])
    assert service.national_team(board)['holdings'][0]['shares_change'] is None
    with database() as db:
        assert db.scalar(select(func.count()).select_from(EtfHolding)) == 2


def test_api_validates_dates_auth_and_exports_saved_observations(database, board, monkeypatch):
    monkeypatch.setattr('src.modules.administration.api.auth.get_password_hash', lambda db: 'configured')
    service.save_board(board, board)
    app = FastAPI()
    app.include_router(api.router, prefix='/api/etf', dependencies=[Depends(get_current_user)])
    client = TestClient(app)
    assert client.get('/api/etf/observations').status_code == 401
    app.dependency_overrides[get_current_user] = lambda: 'test'
    assert client.get('/api/etf/board?date=2099-01-01').status_code == 422
    assert client.get('/api/etf/board?date=bad').status_code == 422
    assert client.get('/api/etf/observations?known_at=2026-01-01T00:00:00').status_code == 422
    assert client.get('/api/etf/observations?limit=101').status_code == 422
    export = client.get('/api/etf/observations?limit=1').json()
    assert export['items'][0]['payload']['etfs'][0]['code'] == '510300'
    assert len(export['items'][0]['checksum']) == 64
    assert export['units']['board_money'] == '100000000 CNY'


def test_historical_knowledge_never_uses_later_market_revisions(database, board, monkeypatch):
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-14T01:00:00+00:00')
    service.save_board(board, board)
    service.save_holdings([report('2025-12-31')])
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-15T01:00:00+00:00')
    revised = copy.deepcopy(board)
    revised['etfs'][0]['net'] = 9
    service.save_board(revised, revised)
    app = FastAPI()
    app.include_router(api.router, prefix='/api/etf')
    client = TestClient(app)
    historical = client.get('/api/etf/national-team', params={'known_at': '2026-11-14T02:00:00Z'})
    assert historical.status_code == 200
    assert historical.json()['watchlist_net_estimate_cny'] == 400_000_000
    assert client.get('/api/etf/national-team', params={'known_at': '2026-11-13T00:00:00Z'}).status_code == 404


@pytest.mark.anyio
async def test_holder_source_parses_only_explicit_institutions(monkeypatch):
    calls = AsyncMock(side_effect=[ '<select id="tc_slt"><option value="2025-12-31">2025</option></select>',
          {'result': {'status': {'code': 0}, 'data': [
              {'cyrmc': '中央汇金投资有限责任公司', 'cyfe': '1000', 'zfeb': '20'},
              {'cyrmc': '中国工商银行股份有限公司－某基金', 'cyfe': '2000', 'zfeb': '40'}]}}])
    monkeypatch.setattr(sources, 'request', calls)
    reports = await sources.holding_reports('510300')
    assert reports[0]['holders'][0]['institution'] == 'huijin'
    assert reports[0]['holders'][1]['institution'] is None


def historical_board(board, day, net):
    value = copy.deepcopy(board)
    value.update(date=day, net=net, series=[], scale=400)
    value['etfs'][0]['net'] = net
    value['etfs'][0]['scale'] = 400
    value['etfs'][0]['peak_window'] = None
    return value


def test_history_range_cumulative_and_missing_days(database, board):
    from src.modules.market.etf import history
    for day, net in [('2026-11-10', 100), ('2026-11-11', 4), ('2026-11-13', -2)]:
        value = historical_board(board, day, net)
        service.save_board(value, value)
    catalog = ['2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13']
    data = history.read_history('2026-11-11', '2026-11-13', catalog)
    assert [p['date'] for p in data['series']] == catalog[1:]
    assert [p['net'] for p in data['series']] == [4, None, -2]
    assert [p['cumulative_net'] for p in data['series']] == [4, None, 2]
    assert data['summary']['net'] == 2 and data['summary']['net_days'] == 2
    assert data['summary']['amount'] == 20 and data['summary']['amount_days'] == 2
    assert data['summary']['missing_net_dates'] == ['2026-11-12']
    assert data['summary']['missing_amount_dates'] == ['2026-11-12']
    assert data['summary']['aggregation'] == 'available_observations'
    assert data['funds'][0]['net'] == 2
    assert data['funds'][0]['days'] == data['funds'][0]['amount_days'] == 2
    value = historical_board(board, '2026-11-12', 1)
    service.save_board(value, value)
    complete = history.read_history('2026-11-11', '2026-11-13', catalog)
    assert complete['summary']['net'] == 3
    assert complete['summary']['inflow'] == 5 and complete['summary']['outflow'] == -2
    assert complete['series'][-1]['cumulative_net'] == 3
    assert complete['funds'][0]['net'] == 3


def test_backfill_preserves_newer_history_revision_and_cutoff(database, board, monkeypatch):
    from src.modules.market.etf import history
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-14T01:00:00+00:00')
    newer = historical_board(board, '2026-11-13', 4)
    newer['series'] = [{'date': '2026-11-12', 'net': 7, 'covered': 1, 'hs300': 4000}]
    service.save_board(newer, newer)
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-15T01:00:00+00:00')
    old = historical_board(board, '2026-11-12', 2)
    service.save_board(old, old)
    result = history.read_history('2026-11-12', '2026-11-13', ['2026-11-12', '2026-11-13'])
    assert result['series'][0]['net'] == 7
    with database() as db:
        assert db.get(EtfFlowDay, '2026-11-12').net_subscription_estimate_cny == 700_000_000
    early = history.read_history('2026-11-12', '2026-11-13', ['2026-11-12', '2026-11-13'], cutoff='2026-11-14T02:00:00+00:00')
    assert early['series'][0]['amount'] is None  # later backfill was not known yet
    assert early['series'][0]['net'] == 7


def test_national_history_keeps_reporting_dates_and_filters_institutions(database, board):
    from src.modules.market.etf import history
    value = historical_board(board, '2026-11-13', 4)
    second = {**value['etfs'][0], 'code': '510050', 'name': '上证50ETF', 'net': 9}
    value['etfs'].append(second);value['covered'] = 2;value['net'] = 13
    service.save_board(value, value)
    service.save_holdings([report('2025-06-30', 80), report('2025-12-31', 100),
                          {**report('2025-12-31', 20, '北京诚通金控投资有限公司'), 'code': '510050'}])
    data = history.read_history('2025-01-01', '2026-11-13', ['2026-11-13'], national=True, institution='huijin')
    assert data['series'][0]['net'] == 4 and data['summary']['funds'] == 1
    assert data['composition_mode'] == 'period_end_disclosed' and data['flow_attribution'] == 'all_etf_investors'
    assert [r['date'] for r in data['holdings_trend']] == ['2025-06-30', '2025-12-31']
    assert data['holdings_trend'][0]['shares'] is None  # missing disclosure coverage is not zero
    assert data['holdings_trend'][1]['shares'] == 100 / 1e8
    assert data['disclosures'][0]['shares_change'] == 20
    recent = history.read_history('2026-08-01', '2026-11-13', ['2026-11-13'], national=True, code='510300')
    assert len(recent['holdings_trend']) == 1
    assert recent['holdings_trend'][0]['date'] == '2025-12-31'
    assert recent['holdings_trend'][0]['before_range'] is True


def test_history_api_validates_range_and_reads_persisted_data(database, board, monkeypatch):
    from src.modules.market.etf import history
    service.save_board(board, board)
    monkeypatch.setattr(service, 'board', AsyncMock(return_value={**service.saved_board(), 'stale': False}))
    monkeypatch.setattr(service, 'dates', AsyncMock(return_value=['2026-11-13', '2026-11-12']))
    monkeypatch.setattr(history, 'collect_range', AsyncMock())
    app = FastAPI();app.include_router(api.router, prefix='/api/etf')
    client = TestClient(app)
    for params in [{'period': 'custom'}, {'start': '2026-11-13', 'end': '2026-11-12'}, {'end': '2099-01-01'},
                   {'code': '../x'}, {'institution': 'unknown'}, {'known_at': '2026-11-14T00:00:00'}]:
        assert client.get('/api/etf/history', params=params).status_code == 422
    data = client.get('/api/etf/history').json()
    assert data['range'] == {'start': '2026-08-13', 'end': '2026-11-13'}
    assert data['summary']['days'] == 2
    assert client.get('/api/etf/history', params={'code': '000000'}).status_code == 404
    assert client.get('/api/etf/history', params={'known_at': '2020-01-01T00:00:00Z'}).status_code == 404


@pytest.mark.anyio
async def test_holding_history_backfill_includes_prior_anchor_and_persists(database, monkeypatch):
    from src.modules.market.etf import history
    monkeypatch.setattr(sources, 'holding_periods', AsyncMock(return_value=['2025-12-31', '2025-06-30', '2024-12-31']))
    async def fetch(code, period):return report(period)
    monkeypatch.setattr(sources, 'holding_report', AsyncMock(side_effect=fetch))
    await history.fill_reports(['510300'], '2025-07-01', '2026-11-13')
    with database() as db:
        assert db.scalar(select(func.count()).select_from(EtfHolding)) == 3
    await history.fill_reports(['510300'], '2025-07-01', '2026-11-13')
    assert sources.holding_report.await_count == 3


def test_partial_historical_coverage_preserves_available_quotes_and_nulls(database, board):
    from src.modules.market.etf import history
    partial = copy.deepcopy(board)
    partial['etfs'].append({**partial['etfs'][0], 'code': '159919', 'net': None, 'scale': None, 'shares_delta': None})
    normalized = sources.validate_board(partial)
    service.save_board(normalized, partial)
    result = history.read_history('2026-11-13', '2026-11-13', ['2026-11-13'])
    assert result['series'][0]['net'] == 4
    assert result['series'][0]['covered'] == 1
    assert result['series'][0]['expected'] == 2
    missing = next(r for r in result['funds'] if r['code'] == '159919')
    assert missing['net'] is None and missing['days'] == 0
    assert missing['amount'] == 10
    assert result['summary']['coverage_min'] == 1
    partial.update(covered=0, net=None, shares_published=False)
    assert sources.validate_board(partial)['net'] is None


@pytest.mark.parametrize('national,code', [(False, None), (False, '510300'), (True, None)])
def test_history_leading_trailing_gaps_zero_and_empty_observations(database, board, national, code):
    from src.modules.market.etf import history
    service.save_holdings([report('2025-12-31')])
    value = historical_board(board, '2026-11-12', 0)
    value['amount'] = 0
    value['etfs'][0]['amount'] = 0
    service.save_board(value, value)
    days = ['2026-11-11', '2026-11-12', '2026-11-13']
    result = history.read_history(days[0], days[-1], days, national=national, code=code)
    assert [p['net'] for p in result['series']] == [None, 0, None]
    assert [p['cumulative_net'] for p in result['series']] == [None, 0, None]
    assert [p['cumulative_net_days'] for p in result['series']] == [0, 1, 1]
    assert result['summary']['net'] == result['summary']['inflow'] == result['summary']['outflow'] == 0
    assert result['summary']['amount'] == 0 and result['summary']['amount_days'] == 1
    assert result['summary']['missing_net_dates'] == ['2026-11-11', '2026-11-13']
    for catalog in [[], ['2026-11-11']]:
        empty = history.read_history(days[0], days[0], catalog, national=national, code=code)
        assert all(empty['summary'][key] is None for key in ['net', 'inflow', 'outflow', 'amount'])
        assert empty['summary']['net_days'] == empty['summary']['amount_days'] == 0
