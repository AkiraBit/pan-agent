import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from test_etf_dashboard import database, board
from src.platform.marketdata import longbridge
from src.platform.persistence.database import get_db
from src.platform.persistence.models import DataSource, LongbridgeObservation
from src.modules.administration.api import datasources
from src.modules.market.data_collector import get_collector_manager


def test_market_observations_are_versioned_and_queryable_by_source(database, monkeypatch):
    monkeypatch.setattr(longbridge, 'SessionLocal', database)
    monkeypatch.setattr(longbridge.time, 'sleep', lambda _: None)
    response = {'content': [{'type': 'text', 'text': '[{"symbol":"AAPL.US","last_done":"100"}]'}]}
    remote = AsyncMock(return_value=response)
    monkeypatch.setattr(longbridge, '_remote', remote)
    args = {'symbols': ['AAPL.US']}
    longbridge.query('quote', args); longbridge.query('quote', args)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(LongbridgeObservation)) == 1
        first = db.scalar(select(LongbridgeObservation))
        first.observed_at = '2026-01-01T00:00:00+00:00'
        db.add(DataSource(name='LB Quote', provider='longbridge', type='quote'))
        db.add(DataSource(name='LB News', provider='longbridge', type='news'))
        db.commit()
        source_id = db.scalar(select(DataSource.id).where(DataSource.type == 'quote'))
        news_id = db.scalar(select(DataSource.id).where(DataSource.type == 'news'))
    remote.return_value = {'content': [{'type': 'text', 'text': '[{"symbol":"AAPL.US","last_done":"101"}]'}]}
    longbridge.query('quote', args)
    app = FastAPI(); app.include_router(datasources.router, prefix='/datasources')
    def session():
        with database() as db: yield db
    app.dependency_overrides[get_db] = session
    client = TestClient(app)
    latest = client.get(f'/datasources/{source_id}/observations?limit=1').json()
    assert latest['items'][0]['payload'][0]['last_done'] == '101'
    assert latest['next_before_id']
    old = client.get(f'/datasources/{source_id}/observations', params={'known_at': '2026-01-02T00:00:00Z'}).json()
    assert old['items'][0]['payload'][0]['last_done'] == '100'
    assert client.get(f'/datasources/{news_id}/observations').json()['items'] == []
    assert client.get(f'/datasources/{source_id}/observations?known_at=2026-01-01T00:00:00').status_code == 422
    with pytest.raises(ValueError): longbridge.query('submit_order', {})


def test_transport_errors_do_not_persist_fake_data_or_expose_provider_body(database, monkeypatch):
    monkeypatch.setattr(longbridge, 'SessionLocal', database)
    monkeypatch.setattr(longbridge.time, 'sleep', lambda _: None)
    monkeypatch.setattr(longbridge, '_remote', AsyncMock(side_effect=ValueError('PRIVATE-token')))
    with pytest.raises(RuntimeError, match='market-data request failed') as error:
        longbridge.query('quote', {'symbols': ['AAPL.US']})
    assert 'PRIVATE' not in str(error.value)
    with database() as db:
        assert db.scalar(select(func.count()).select_from(LongbridgeObservation)) == 0


@pytest.mark.anyio
async def test_source_test_uses_longbridge_only(database, monkeypatch):
    calls = []
    def query(tool, args):
        calls.append((tool, args))
        return [{'symbol': '510300.SH', 'last_done': '4', 'timestamp': '2026-11-13T15:00:00+08:00'}]
    monkeypatch.setattr(longbridge, 'query', query)
    source = DataSource(name='Longbridge', type='quote', provider='longbridge', enabled=True,
                        config={}, test_symbols=['510300'])
    result = await get_collector_manager().test_source(source)
    assert result.success and result.data[0]['source'] == 'longbridge'
    assert calls == [('quote', {'symbols': ['510300.SH']})]


def test_partial_money_flow_summary_retains_source_and_unknown_main(monkeypatch):
    from marketdata.types import CapitalFlow
    from src.platform.marketdata.collectors import capital_flow_collector as collector
    from src.platform.marketdata.models import MarketCode
    from types import SimpleNamespace
    value = CapitalFlow(symbol='AAPL', name='Apple', big_net_inflow=3, source='longbridge',
                        measurement='longbridge_order_size', currency='USD')
    monkeypatch.setattr(collector, 'get_market_data', lambda: SimpleNamespace(capital_flow=lambda *a, **k: value))
    summary = collector.CapitalFlowCollector(MarketCode.US).get_capital_flow_summary('AAPL')
    assert summary['main_net_inflow'] is None and summary['big_net_inflow'] == 3
    assert summary['currency'] == 'USD' and summary['measurement'] == 'longbridge_order_size'
