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
