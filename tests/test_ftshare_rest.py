import asyncio
import json
from collections import Counter
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import reconcile_data_sources
from src.bootstrap.application import app
from src.modules.administration.api import auth
from src.platform.marketdata import ftshare_rest as ftshare
from src.platform.marketdata import provider_credentials
from src.platform.persistence import database
from src.platform.persistence.models import AppSettings, DataSource

KEY = "ftshare_sk_test-credential-not-real"
BASE = "/api/datasources/ftshare"


def test_all_official_free_and_basic_examples_fit_their_own_request_contract(monkeypatch):
    operations = ftshare.CATALOG["operations"]
    assert Counter(op["tier"] for op in operations) == {"free": 168, "basic": 57}
    assert len(ftshare.OPERATIONS) == 225
    variants = [(op, i, spec) for op in operations for i, spec in enumerate(op["variants"])]
    assert len({spec["path"] for _, _, spec in variants}) == len(variants)
    sent = []

    def upstream(req):
        assert req.method == "GET"
        assert req.url.host == "market.ft.tech" and req.url.scheme == "https"
        assert req.headers["FTSHARE_API_KEY"] == KEY
        assert "authorization" not in req.headers
        sent.append((req.url.path, dict(req.url.params)))
        return httpx.Response(200, content=b'{"code":200,"message":"success","data":[9223372036854775807]}')

    monkeypatch.setattr(ftshare, "http_client", lambda key: httpx.AsyncClient(
        headers={"FTSHARE_API_KEY": key}, transport=httpx.MockTransport(upstream)))
    async def exercise():
        for operation, index, spec in variants:
            assert urlsplit(operation["docs_url"]).hostname == "market.ft.tech"
            result = await ftshare.query(operation["id"], {"variant": index}, KEY)
            assert ftshare.successful(result)
            assert "9223372036854775807" in result["response_json"]
            assert sent[-1] == ("/gateway" + spec["path"], ftshare.preset(spec))
    asyncio.run(exercise())


def test_request_modes_and_invalid_fields_are_checked():
    quote = ftshare.OPERATIONS["stock_adjust_factor"]
    with pytest.raises(ftshare.InvalidQuery):
        ftshare.validate(quote, {"params": {"symbol": "600000.SH", "trade_date": "20260230"}})
    with pytest.raises(ftshare.InvalidQuery):
        ftshare.validate(quote, {"params": {"limit": "12"}})
    with pytest.raises(ftshare.InvalidQuery):
        ftshare.validate(quote, {"params": {"page_size": "2001"}})
    variants = ftshare.OPERATIONS["stock_daec_stocks"]
    assert len(variants["variants"]) == 7
    with pytest.raises(ftshare.InvalidQuery):
        ftshare.validate(variants, {"variant": 6, "params": {"filter": "close > 2"}})
    with pytest.raises(ftshare.InvalidQuery):
        ftshare.validate(variants, {"variant": 99})
    futures = ftshare.OPERATIONS["futures_minutes"]
    documented = futures["variants"][0]["preset"]
    with pytest.raises(ftshare.InvalidQuery):
        ftshare.validate(futures, {"params": {**documented, "symbols": "CU2611.SHFE"}})


def test_catalog_settings_probe_credential_and_pauses(tmp_path, monkeypatch):
    from pan_agent import ToolExposure, ToolRegistry
    from src.modules.assistant.market_rest_tools import ftshare_tool_descriptors, register_ftshare_rest_tools

    engine = create_engine(f"sqlite:///{tmp_path / 'ftshare.db'}")
    database.Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add(AppSettings(key=auth.PASSWORD_HASH_KEY, value="configured"))
        reconcile_data_sources(db)
        reconcile_data_sources(db)
        assert db.query(DataSource).filter_by(provider="ftshare").count() == 225
        source = db.query(DataSource).filter_by(provider="ftshare", type="ftshare:get_stock_share").one()
        source_id = source.id
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(provider_credentials, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(auth, "get_jwt_secret", lambda: "ftshare-test-signing-key" * 4)

    calls = []
    def upstream(req):
        calls.append(req)
        assert req.headers["FTSHARE_API_KEY"] == KEY
        assert req.url.path == "/gateway/api/v2/market/data/share/get-stock-share"
        return httpx.Response(200, json={"code": 200, "message": KEY, "data": {"items": []}})
    monkeypatch.setattr(ftshare, "http_client", lambda key: httpx.AsyncClient(
        headers={"FTSHARE_API_KEY": key}, transport=httpx.MockTransport(upstream)))

    client = TestClient(app)
    assert client.get(BASE + "/catalog").status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_token()[0]
    source_path = f"/api/datasources/{source_id}"
    invoke = BASE + "/query/get_stock_share"
    config = {"variant": 0, "params": {"date": "20260716", "stock_code": "600519.SH", "page_size": "10"}}
    assert client.post(invoke, json=config).status_code == 409
    assert client.put("/api/settings/data-providers/ftshare", json={"api_key": KEY}).status_code == 200
    metadata = client.get(source_path).json()["data"]
    assert metadata["ftshare_operation"]["tier"] == "basic" and metadata["connection_status"] == "ready"
    assert client.put(source_path, json={"config": {"params": {"api_key": "change"}}}).status_code == 422
    assert client.put(source_path, json={"type": "quote"}).status_code == 422
    result = client.put(source_path, json={"config": config})
    assert result.status_code == 200
    assert result.json()["data"]["config"] == config
    assert not calls

    probe = client.post(source_path + "/test")
    assert probe.status_code == 200, probe.text
    result = probe.json()["data"]
    assert result["test_passed"] and result["ftshare_tier"] == "basic" and result["business_code"] == 200
    assert KEY not in probe.text and "[redacted]" in result["raw_response"]
    assert dict(calls[-1].url.params) == config["params"]

    catalog = client.get(BASE + "/catalog")
    assert KEY not in catalog.text
    assert next(op for op in catalog.json()["data"]["operations"] if op["id"] == "get_stock_share")["settings"] == config
    rest = client.post(invoke, json=config).json()["data"]
    name = "ftshare_rest_get_stock_share"
    registry = ToolRegistry()
    with sessions() as db:
        register_ftshare_rest_tools(registry, db)
    assert len(registry.registered_tools()) == 225
    assert next(tool for tool in registry.registered_tools() if tool.name == name).exposure == ToolExposure.DEFERRED
    assert name in {descriptor.tool_name for descriptor in ftshare_tool_descriptors(registry)}
    agent = asyncio.run(registry.execute(name, None, config))
    assert agent.ok and agent.data["response_json"] == rest["response_json"]
    assert json.loads(agent.summary)["data"] == {"items": []}
    assert client.put(source_path, json={"enabled": False}).status_code == 200
    assert client.post(invoke, json=config).status_code == 409
    assert asyncio.run(registry.execute(name, None, config)).error_code == "datasource_operation_disabled"
    assert client.put(source_path, json={"enabled": True}).status_code == 200
    assert client.put("/api/datasources/providers/ftshare", json={"enabled": False}).status_code == 200
    assert client.post(source_path + "/test").status_code == 409
    assert client.post(invoke, json=config).status_code == 409
    assert asyncio.run(registry.execute(name, None, config)).error_code == "datasource_provider_paused"
    assert len(calls) == 3
    client.close()
    engine.dispose()


def test_ftshare_primary_only_falls_back_to_fuyao(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from marketdata import Quote
    from src.platform.marketdata import ftshare_market, fuyao_native, marketdata_client
    from src.platform.marketdata.collectors.kline_collector import KlineCollector
    from src.platform.marketdata.models import MarketCode

    engine = create_engine(f"sqlite:///{tmp_path / 'ftshare-routing.db'}")
    database.Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add(AppSettings(key=auth.PASSWORD_HASH_KEY, value="configured"))
        reconcile_data_sources(db)
        same_contract = db.query(DataSource).filter_by(type="fuyao:get_a_share_prices_snapshot", provider="fuyao").one()
        other = db.query(DataSource).filter_by(type="quote", provider="tencent").one()
        primary = db.query(DataSource).filter_by(type="ftshare:stock_daec_stocks").one()
        same_contract.enabled, same_contract.priority, primary.priority, other.priority = True, 0, 50, -100
        fuyao_id, other_id, ft_id = same_contract.id, other.id, primary.id
        db.query(DataSource).filter_by(type="fuyao:get_a_share_index_prices_historical", provider="fuyao").update({"enabled": True})
        db.commit()

    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(provider_credentials, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(auth, "get_jwt_secret", lambda: "ftshare-routing-key" * 4)
    monkeypatch.setattr(marketdata_client, "_md", None)
    app_client = TestClient(app)
    app_client.headers["Authorization"] = "Bearer " + auth.create_token()[0]
    app_client.put("/api/settings/data-providers/ftshare", json={"api_key": KEY}).raise_for_status()
    app_client.put("/api/settings/data-providers/fuyao", json={"api_key": "fixture-fuyao-key"}).raise_for_status()
    attempted = []
    should_fail = False

    def response(req):
        attempted.append("ftshare")
        assert req.headers["FTSHARE_API_KEY"] == KEY
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        if req.url.path.endswith("/stock-candlesticks"):
            assert req.url.params["limit"] == "1"
            return httpx.Response(200, json={"code": 200, "data": [{
                "ts_millis": ts, "open": 10, "close": 11, "high": 12, "low": 9, "volume": 10000,
            }]})
        assert req.url.path == "/gateway/api/v1/market/data/daec/stocks/all"
        symbols = req.url.params["filter"]
        assert '600519.XSHG' in symbols or '000001.XSHE' in symbols
        if should_fail:
            return httpx.Response(503)
        return httpx.Response(200, json={"code": 200, "data": {"items": [{
            "symbol": "600519.XSHG", "close": "15.8", "change_rate": 0.031, "ts_millis": ts,
        }]}})

    monkeypatch.setattr(ftshare_market, "client", lambda key, timeout: httpx.Client(
        headers={"FTSHARE_API_KEY": key}, transport=httpx.MockTransport(response)))
    md = marketdata_client.get_market_data()

    def fuyao(symbols, config):
        attempted.append("fuyao")
        assert [symbol.code for symbol in symbols] == ["000001"]
        return [Quote(symbol="000001", market="CN", current_price=10.0)]

    def tencent(*args):
        attempted.append("tencent")
        return []

    monkeypatch.setattr(md._quote_engine.vendors["fuyao"], "fetch", fuyao)
    monkeypatch.setattr(md._quote_engine.vendors["tencent"], "fetch", tencent)
    monkeypatch.setattr(md._kline_engine.vendors["fuyao"], "fetch", lambda *_: [])
    rows = md.quotes(["600519"], market="CN")
    assert [(q.source, q.change_pct) for q in rows] == [("ftshare", 3.1)]
    assert attempted == ["ftshare"]
    assert KlineCollector(MarketCode.CN)._fetch_all_sources("600519", 1)[0].source == "ftshare"
    should_fail = True
    assert [q.source for q in md.quotes(["000001"], market="CN")] == ["fuyao"]
    assert attempted == ["ftshare", "ftshare", "ftshare", "fuyao"]

    def failed_index(provider):
        attempted.append(provider)
        return []
    assert fuyao_native.first("index_kline", {provider: lambda p=provider: failed_index(p)
        for provider in ("eastmoney", "fuyao", "ftshare", "tencent")}) is None
    assert attempted[-2:] == ["ftshare", "fuyao"]

    for source_id, mode in ((ft_id, "fallback"), (fuyao_id, "fallback"), (other_id, "direct")):
        path = f"/api/datasources/{source_id}"
        assert app_client.get(path).json()["data"]["routing"]["mode"] == mode
        assert app_client.post(path + "/move", json={"direction": "first"}).status_code == 409
        assert app_client.put(path, json={"priority": -10}).status_code == 409
    assert app_client.get(f"/api/datasources/{ft_id}").json()["data"]["priority"] == 0
    assert app_client.get(f"/api/datasources/{fuyao_id}").json()["data"]["priority"] == 1

    app_client.put("/api/datasources/providers/ftshare", json={"enabled": False}).raise_for_status()
    assert [q.source for q in md.quotes(["000001"], market="CN")] == ["fuyao"]
    app_client.put("/api/datasources/providers/fuyao", json={"enabled": False}).raise_for_status()
    assert md.quotes(["600519"], market="CN") == []
    assert "tencent" not in attempted and "eastmoney" not in attempted
    assert [s.vendor for s in marketdata_client.DbConfigProvider().sources_for("quote", "HK")] == ["tencent"]
    app_client.close()
    engine.dispose()


def test_ftshare_bars_and_calendar_preserve_coverage_and_adjustment(monkeypatch):
    from datetime import date, datetime
    from marketdata.symbol import Symbol
    from src.platform.marketdata import ftshare_market as market

    captured = []
    today = datetime.now(market.CN)
    def payload(operation, params, **kwargs):
        captured.append((operation, params))
        if operation == "trading_calendar":
            return {**params, "trade_dates": ["20261116", "20261117"]}
        return [{"ts_millis": int(today.timestamp() * 1000), "open": "10", "close": "11", "high": "12",
                 "low": "9", "volume": 10000, "turnover": "108000.0"}]
    monkeypatch.setattr(market, "data", payload)
    rows = market.FtshareKlineVendor().fetch([Symbol.parse("600519", "CN")], {"days": 20})
    assert rows[0].source == "ftshare" and rows[0].turnover == 108000
    assert (captured[0][1]["symbol"], captured[0][1]["adjust_kind"]) == ("600519.XSHG", "forward")
    assert market.index_bars("000300", 20)[0].date == today.date().isoformat()
    assert (captured[1][1]["symbol"], captured[1][1]["adjust_kind"]) == ("000300.SH", "none")
    opened = market.open_days("HK", date(2026, 11, 16), date(2026, 11, 17))
    assert opened == {date(2026, 11, 16), date(2026, 11, 17)}
    with pytest.raises(market.SourceFailure, match="outside"):
        market.open_days("HK", date(2026, 11, 16), date(2026, 11, 16))
