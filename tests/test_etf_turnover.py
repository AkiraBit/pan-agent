import asyncio
import copy
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from test_etf_dashboard import database, board, report
from src.modules.market.etf import history, service, turnover
from src.modules.market.etf.models import EtfDaily, EtfSnapshot, EtfTurnover
from src.platform.persistence.models import DataSource, MCPConnection


def bar(day='2026-11-13', amount='123456789.25'):
    return {'timestamp': day + 'T00:00:00+08:00', 'turnover': amount, 'volume': '1234'}


def result(rows):
    return {'content': [{'type': 'text', 'text': json.dumps(rows)}]}


def missing_board(value):
    value = copy.deepcopy(value)
    value['amount'] = value['etfs'][0]['amount'] = None
    return value


def enable(factory):
    with factory() as db:
        db.add(DataSource(name='Longbridge ETF', provider='longbridge', type='etf_turnover', enabled=True))
        db.add(MCPConnection(provider='longbridge', credentials='encrypted-fixture', enabled=True))
        db.commit()


def test_fill_units_revision_restart_history_and_knowledge_cutoff(database, board, monkeypatch):
    board = missing_board(board)
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-14T00:00:00+00:00')
    original = service.save_board(board, board)
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-15T00:00:00+00:00')
    rows = turnover.decode(result([bar()]), '510300', board['date'], board['date'])
    assert turnover.save(rows, {board['date']}) == 1
    turnover.save(rows, {board['date']})
    service._checked.clear()  # No in-memory cache is required for reads.
    with database() as db:
        assert db.get(EtfDaily, ('510300', board['date'])).turnover_cny == 123456789.25
        assert db.get(EtfSnapshot, original).payload['amount'] is None
        assert db.scalar(select(func.count()).select_from(EtfTurnover)) == 1
        assert db.scalar(select(func.count()).select_from(EtfSnapshot).where(EtfSnapshot.resource == 'turnover')) == 1
    service.save_board(board, board)  # A later primary-source null must not erase the supplement.
    saved = service.saved_board(board['date'])['payload']
    assert saved['amount'] == 1.2345678925
    assert saved['etfs'][0]['amount_source'] == 'longbridge'
    assert service.saved_board(board['date'], '2026-11-14T12:00:00+00:00')['payload']['amount'] is None
    for code in (None, '510300'):
        data = history.read_history(board['date'], board['date'], [board['date']], code=code)
        assert data['summary']['amount_days'] == 1
        assert data['summary']['amount'] == saved['amount']
        assert data['series'][0]['amount_snapshot_ids']
    service.save_holdings([report('2025-12-31')])
    assert history.read_history(board['date'], board['date'], [board['date']], national=True)['summary']['amount_days'] == 1
    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-16T00:00:00+00:00')
    turnover.save(turnover.decode(result([bar(amount='0')]), '510300', board['date'], board['date']), {board['date']})
    assert service.saved_board()['payload']['amount'] == 0
    assert service.saved_board(knowledge_cutoff='2026-11-15T12:00:00+00:00')['payload']['amount'] == saved['amount']


def test_primary_precedence_and_incomplete_basket(database, board):
    value = missing_board(board)
    value['etfs'].append({**value['etfs'][0], 'code': '159919'})
    service.save_board(value, value)
    rows = turnover.decode(result([bar()]), '510300', board['date'], board['date'])
    turnover.save(rows, {board['date']})
    assert service.saved_board()['payload']['amount'] is None
    assert service.saved_board()['payload']['etfs'][0]['amount'] is not None
    # A newly published primary measurement takes precedence, without deleting evidence.
    service.save_board(board, board)
    turnover.save(rows, {board['date']})
    assert service.saved_board()['payload']['amount'] == 10
    with database() as db:
        assert db.get(EtfDaily, ('510300', board['date'])).turnover_cny == 1e9


@pytest.mark.parametrize('rows', [[bar(amount='NaN')], [bar(amount='-1')], [bar(amount=True)],
    [bar('2026-11-12')], [bar(), bar()], [{'timestamp': '2026-11-13', 'turnover': '1'}],
    [{**bar(), 'symbol': '159919.SZ'}]])
def test_rejects_corrupt_or_mismatched_measurements(rows):
    with pytest.raises(ValueError):
        turnover.decode(result(rows), '510300', '2026-11-13', '2026-11-13')


@pytest.mark.anyio
async def test_collect_respects_connection_source_controls_and_recovers(database, board, monkeypatch):
    value = missing_board(board)
    service.save_board(value, value)
    fetch = AsyncMock(return_value=turnover.decode(result([bar()]), '510300', board['date'], board['date']))
    monkeypatch.setattr(turnover, 'fetch', fetch)
    monkeypatch.setattr(turnover, 'last_closed_day', lambda: board['date'])
    assert await turnover.collect() == 0
    fetch.assert_not_awaited()
    enable(database)
    with database() as db:
        source = db.scalar(select(DataSource))
        source.enabled = False
        db.commit()
    assert await turnover.collect() == 0
    fetch.assert_not_awaited()
    with database() as db:
        db.scalar(select(DataSource)).enabled = True
        db.commit()
    await asyncio.gather(turnover.collect(), turnover.collect())
    assert fetch.await_count == 1
    # Durable completion prevents redundant requests after the process cache is reset.
    service._checked.clear(); service._retry.clear()
    assert await turnover.collect() == 0
    assert fetch.await_count == 1


@pytest.mark.anyio
async def test_partial_or_failed_response_keeps_gaps_retryable(database, board, monkeypatch):
    value = missing_board(board)
    value['etfs'].append({**value['etfs'][0], 'code': '159919'})
    service.save_board(value, value)
    enable(database)
    monkeypatch.setattr(turnover, 'last_closed_day', lambda: board['date'])
    async def fetch(code, start, end):
        if code == '159919': raise RuntimeError('offline')
        return turnover.decode(result([bar()]), code, start, end)
    monkeypatch.setattr(turnover, 'fetch', fetch)
    assert await turnover.collect() == 1
    with database() as db:
        assert db.get(EtfDaily, ('159919', board['date'])).turnover_cny is None
    service._retry.clear()
    monkeypatch.setattr(turnover, 'fetch', AsyncMock(return_value=turnover.decode(result([bar()]), '159919', board['date'], board['date'])))
    assert await turnover.collect() == 1


@pytest.mark.anyio
async def test_rate_limit_retries_and_bounded_history(database, monkeypatch):
    provider = AsyncMock(side_effect=[result({'error_code': 429002}), result([bar()])])
    monkeypatch.setattr(turnover.longbridge_mcp, 'remote', provider)
    monkeypatch.setattr(turnover.asyncio, 'sleep', AsyncMock())
    assert len(await turnover.fetch('510300', '2026-11-13', '2026-11-13')) == 1
    assert provider.await_count == 2
    assert provider.call_args.args[2]['forward_adjust'] is False
    assert list(turnover.batches(['2026-01-01', '2026-01-02', '2026-05-01'])) == [
        ['2026-01-01', '2026-01-02'], ['2026-05-01']]


@pytest.mark.anyio
async def test_disabling_source_stops_remaining_requests(database, board, monkeypatch):
    value = missing_board(board)
    value['etfs'].append({**value['etfs'][0], 'code': '159919'})
    service.save_board(value, value)
    enable(database)
    monkeypatch.setattr(turnover, 'last_closed_day', lambda: board['date'])
    calls = []
    async def fetch(code, start, end):
        calls.append(code)
        with database() as db:
            db.scalar(select(DataSource)).enabled = False
            db.commit()
        return turnover.decode(result([bar()]), code, start, end)
    monkeypatch.setattr(turnover, 'fetch', fetch)
    assert await turnover.collect() == 1
    assert len(calls) == 1
