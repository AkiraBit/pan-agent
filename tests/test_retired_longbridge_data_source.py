from sqlalchemy import select

from test_datasource_admin_api import _client
from src.modules.administration import builtin_skills
from src.platform.marketdata.marketdata_client import DbConfigProvider
from src.platform.persistence import database
from src.platform.persistence.migrations import _m150_retire_longbridge_data_sources
from src.platform.persistence.models import DataSource, DataSourceProviderPause, LongbridgeObservation, MCPConnection


def test_legacy_rows_are_inactive_even_before_cleanup(monkeypatch):
    client, Session = _client()
    monkeypatch.setattr(database, "SessionLocal", Session)
    with Session() as db:
        db.add_all([
            DataSource(id=1, name="Longbridge", type="quote", provider="longbridge", enabled=True),
            DataSource(id=2, name="Tencent", type="quote", provider="tencent", enabled=True),
            MCPConnection(provider="longbridge", enabled=True, credentials="encrypted-fixture"),
        ])
        db.commit()

    api = "/api/datasources"
    assert [row["provider"] for row in client.get(api).json()] == ["tencent"]
    assert client.get(f"{api}/1").status_code == 404
    assert client.post(f"{api}/1/test").status_code == 404
    assert client.get(f"{api}/1/observations").status_code == 404
    assert client.put(f"{api}/providers/longbridge", json={"enabled": True}).status_code == 404
    assert client.post(api, json={"name": "Longbridge", "type": "quote", "provider": "longbridge"}).status_code == 422
    assert [source.vendor for source in DbConfigProvider().sources_for("quote", "US")] == ["tencent"]


def test_cleanup_preserves_mcp_authorization_skill_switch_and_observations():
    from server import reconcile_data_sources

    _, Session = _client()
    with Session() as db:
        db.add_all([
            DataSource(id=1, name="Longbridge", type="quote", provider="longbridge", enabled=True),
            DataSource(id=2, name="Tencent", type="quote", provider="tencent", enabled=False),
            DataSourceProviderPause(provider="longbridge"),
            DataSourceProviderPause(provider="sina"),
            MCPConnection(provider="longbridge", enabled=True, credentials="encrypted-fixture"),
            LongbridgeObservation(tool="quote", request_key="saved-quote", arguments={}, payload=[],
                                  checksum="fixture", observed_at="2026-11-13T08:00:00Z"),
        ])
        db.commit()
        assert builtin_skills.configure(db, True)["enabled"] is True
        _m150_retire_longbridge_data_sources(db.connection())
        db.commit()
        reconcile_data_sources(db, reset_test_symbols=True)
        assert db.get(DataSource, 1) is None and db.get(DataSource, 2).enabled is False
        assert db.get(DataSourceProviderPause, "longbridge") is None
        assert db.get(DataSourceProviderPause, "sina") is not None
        assert db.get(MCPConnection, "longbridge").credentials == "encrypted-fixture"
        assert db.get(MCPConnection, "longbridge").enabled is True
        assert builtin_skills.status(db)["enabled"] is True
        assert db.scalar(select(LongbridgeObservation.request_key)) == "saved-quote"


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
