"""数据源管理端点新增能力:is_orphan 标记 + POST /reset-to-seed 温和对账。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.modules.administration.api.datasources as ds
import src.platform.persistence.models as M  # noqa: F401  确保模型注册到 Base.metadata
from src.platform.persistence.database import Base, get_db
from src.platform.persistence.models import DataSource


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(ds.router, prefix="/api/datasources")

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return TestClient(app), Session


def test_is_orphan_flags_orphan_and_normal_rows_correctly():
    """is_orphan: 孤儿 provider(news/cls)标 True,正常 seed provider(quote/tencent)标 False。"""
    from types import SimpleNamespace

    orphan_row = SimpleNamespace(
        id=1, name="财联社电报", type="news", provider="cls",
        config={}, enabled=True, priority=0, supports_batch=False, test_symbols=[],
    )
    normal_row = SimpleNamespace(
        id=2, name="腾讯行情", type="quote", provider="tencent",
        config={}, enabled=True, priority=0, supports_batch=True, test_symbols=[],
    )

    assert ds._to_response(orphan_row)["is_orphan"] is True
    assert ds._to_response(normal_row)["is_orphan"] is False


def test_provider_pause_skips_all_adapters_and_preserves_endpoint_configuration(monkeypatch):
    from src.platform.marketdata import fuyao_business
    from src.platform.marketdata.marketdata_client import DbConfigProvider
    from src.modules.research.signals.signal_pack import SignalPackBuilder
    from src.platform.persistence import database

    client, Session = _client()
    monkeypatch.setattr(database, "SessionLocal", Session)
    with Session() as db:
        db.add_all([
            DataSource(id=1, name="East Money quote", type="quote", provider="eastmoney", enabled=True, priority=0),
            DataSource(id=2, name="East Money news", type="news", provider="eastmoney_news", enabled=True, priority=7),
            DataSource(id=3, name="East Money candles", type="kline", provider="eastmoney", enabled=False, priority=5),
            DataSource(id=4, name="Tencent quote", type="quote", provider="tencent", enabled=True, priority=10),
        ])
        db.commit()

    api = "/api/datasources"
    config = DbConfigProvider()
    assert [s.vendor for s in config.sources_for("quote", "CN")] == []
    assert [s.vendor for s in config.sources_for("news", "CN")] == ["eastmoney_news"]
    assert client.put(f"{api}/providers/eastmoney", json={"enabled": False}).json() == {"provider": "eastmoney", "enabled": False}
    assert client.get(f"{api}/providers").json() == {"paused": ["eastmoney"]}
    assert [s.vendor for s in config.sources_for("quote", "HK")] == ["tencent"]
    assert config.sources_for("news", "CN") == []
    assert fuyao_business.providers("market_sentiment") == []
    assert SignalPackBuilder._source_policy("events", default_providers=["eastmoney"]) == ([], True)
    assert client.post(f"{api}/2/test").status_code == 409
    assert client.get(f"{api}/2").json()["provider_group"] == "eastmoney"
    assert client.get(f"{api}/2").json()["enabled"] is True
    assert client.get(f"{api}/2").json()["priority"] == 7

    assert client.put(f"{api}/providers/eastmoney_news", json={"enabled": True}).status_code == 200
    assert client.get(f"{api}/providers").json() == {"paused": []}
    assert [s.vendor for s in config.sources_for("quote", "CN")] == []
    assert [s.vendor for s in config.sources_for("news", "CN")] == ["eastmoney_news"]
    assert config.sources_for("kline", "CN") == []
    assert fuyao_business.providers("market_sentiment") == ["eastmoney"]


def test_registered_provider_can_be_paused_without_any_endpoints():
    client, _ = _client()
    api = "/api/datasources/providers"
    assert client.put(f"{api}/ftshare", json={"enabled": False}).status_code == 200
    assert client.get(api).json() == {"paused": ["ftshare"]}
    assert client.put(f"{api}/unknown", json={"enabled": False}).status_code == 404


def test_bulk_endpoint_switch_updates_only_the_selected_catalog_and_preserves_settings(monkeypatch):
    client, Session = _client()
    with Session() as db:
        db.add_all([
            DataSource(id=1, provider="fuyao", type="fuyao:get_a_share_prices_snapshot", name="Snapshot",
                       enabled=True, config={"params": {"thscodes": "600519.SH"}}),
            DataSource(id=2, provider="fuyao", type="fuyao:get_a_share_prices_historical", name="History", enabled=False),
            DataSource(id=3, provider="ths", type="northbound", name="Northbound", enabled=True),
            DataSource(id=4, provider="ftshare", type="ftshare:stock_candlesticks", name="FTShare", enabled=True),
        ])
        db.commit()

    base = "/api/datasources/providers"
    path = base + "/fuyao/endpoints"
    assert client.put(path, json={"enabled": False}).json()["source_ids"] == [1, 2]
    assert client.put(path, json={"enabled": True}).status_code == 409  # Same key requirement as an individual switch.
    with Session() as db:
        assert [db.get(DataSource, i).enabled for i in (1, 2, 3, 4)] == [False, False, True, True]
    monkeypatch.setattr(ds.fuyao_credentials, "decrypt", lambda _: "fixture-key")
    assert client.put(path, json={"enabled": True}).json() == {
        "provider": "fuyao", "enabled": True, "source_ids": [1, 2],
    }
    assert client.get(base).json() == {"paused": []}
    client.put(base + "/fuyao", json={"enabled": False}).raise_for_status()
    assert client.put(path, json={"enabled": False}).status_code == 409
    with Session() as db:
        assert [db.get(DataSource, i).enabled for i in (1, 2, 3, 4)] == [True, True, True, True]
        assert db.get(DataSource, 1).config == {"params": {"thscodes": "600519.SH"}}


def test_retired_sources_are_removed_and_public_routes_keep_their_configuration():
    from src.platform.persistence.migrations import _m147_retire_data_sources
    from src.platform.persistence.models import AppSettings, DataSourceProviderPause

    client, Session = _client()
    with Session() as db:
        db.add_all([
            DataSource(id=11, provider="public", type="stock_search", name="Old search", enabled=False, priority=9),
            DataSource(id=12, provider="sse", type="etf_shares", name="Old ETF shares", enabled=True, priority=0),
            DataSource(id=13, provider="xueqiu", type="news", name="Old news", enabled=True, priority=0),
            DataSource(id=14, provider="cls", type="flash_news", name="CLS", enabled=True, priority=3),
            DataSourceProviderPause(provider="xueqiu"), DataSourceProviderPause(provider="cls"),
            AppSettings(key="stock_link_platform", value="xueqiu"),
        ])
        db.commit()
        with db.get_bind().begin() as conn:
            _m147_retire_data_sources(conn)
            _m147_retire_data_sources(conn)
        migrated = db.get(DataSource, 11)
        assert (migrated.provider, migrated.enabled, migrated.priority) == ("eastmoney", False, 9)
        assert db.get(DataSource, 12) is None and db.get(DataSource, 13) is None
        assert db.get(DataSource, 14).priority == 3
    assert client.get("/api/datasources/providers").json() == {"paused": ["cls"]}
    assert client.put("/api/datasources/providers/xueqiu", json={"enabled": True}).status_code == 404


def test_reset_to_seed_endpoint_deletes_orphan_and_returns_summary():
    """POST /reset-to-seed: 冒烟 —— 删孤儿行、返回 summary(经中间件包裹前的原始 dict)。"""
    client, Session = _client()

    db = Session()
    db.add(
        DataSource(
            name="财联社电报", type="news", provider="cls", config={},
            enabled=True, priority=0, supports_batch=False, test_symbols=[],
        )
    )
    db.commit()
    db.close()

    resp = client.post("/api/datasources/reset-to-seed")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    deleted_pairs = {(d["type"], d["provider"]) for d in body["deleted"]}
    assert ("news", "cls") in deleted_pairs
    assert "seeded_missing" in body

    db2 = Session()
    remaining = {(s.type, s.provider) for s in db2.query(DataSource).all()}
    assert ("news", "cls") not in remaining
    # 缺失的默认(如东财K线)应被补回
    assert ("kline", "eastmoney") in remaining
    db2.close()


@pytest.mark.parametrize(("provider", "wire"), [("cls", "rn"), ("sina", "page_size"), ("eastmoney", "pageSize")])
def test_market_wide_probe_forwards_saved_limit_and_ignores_legacy_symbols(monkeypatch, provider, wire):
    from marketdata.vendors import flash_news

    client, Session = _client()
    with Session() as db:
        db.add(DataSource(id=1, name="Headlines", type="flash_news", provider=provider, enabled=True,
                          config={"description": "preserve me"}, test_symbols=["600519"]))
        db.commit()

    sent = []
    def upstream(url, *, params, **kwargs):
        sent.append(params)
        return {}

    monkeypatch.setattr(flash_news, "market_get", upstream)
    path = "/api/datasources/1"
    settings = client.get(path).json()["test_settings"]
    assert settings["symbols"] is None and settings["test_symbols"] == []
    assert settings["fields"][0]["wire"] == wire
    assert settings["fields"][0]["default"] == 20
    assert client.put(path, json={"test_params": {"limit": 51}}).status_code == 422
    assert client.put(path, json={"test_params": {"limit": "7"}}).json()["config"] == {
        "description": "preserve me", "test_params": {"limit": 7},
    }
    result = client.post(f"{path}/test").json()
    assert result["test_params"] == {"limit": 7} and result["test_symbols"] == []
    assert len(sent) == 1 and sent[0][wire] == 7


def test_eastmoney_event_probe_sends_configured_page_size_to_its_own_endpoint(monkeypatch):
    from marketdata.vendors import events

    client, Session = _client()
    with Session() as db:
        db.add(DataSource(id=1, name="Events", type="events", provider="eastmoney",
                          config={}, test_symbols=["600519", "AAPL"]))
        db.commit()

    sent = []
    def upstream(url, *, params, **kwargs):
        sent.append(params)
        return {"success": True, "data": {"list": []}}
    monkeypatch.setattr(events, "market_get", upstream)

    path = "/api/datasources/1"
    assert client.get(path).json()["test_settings"]["test_symbols"] == ["600519"]
    assert client.put(path, json={"test_params": {"page_size": 12, "lookback_days": 10},
                                  "test_symbols": ["AAPL"]}).status_code == 422
    assert client.put(path, json={"test_params": {"page_size": 12, "lookback_days": 10},
                                  "test_symbols": ["600519"]}).status_code == 200
    assert client.post(f"{path}/test").json()["test_params"] == {"page_size": 12, "lookback_days": 10}
    assert len(sent) == 1 and sent[0]["page_size"] == 12 and sent[0]["stock_list"] == "600519"
