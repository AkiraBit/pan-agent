"""PanWatch's shared credential and both provider protocols, without live API access."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from marketdata.vendors import fuyao
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.bootstrap.application import app
from src.modules.administration import mcp_transport
from src.modules.administration.api import auth
from src.modules.assistant.fuyao_tools import _tool_name, register_fuyao_rest_tools, register_fuyao_tools
from src.platform.marketdata import fuyao_business, fuyao_credentials, fuyao_rest, marketdata_client, stock_list
from src.platform.marketdata import provider_credentials
from src.platform.persistence import database
from src.platform.persistence.models import AppSettings, DataSource
from pan_agent import ToolRegistry

KEY = "fixture-shared-key"
ROTATED = "fixture-rotated-key"
CREDENTIAL = "/api/settings/data-providers/fuyao"
MCP = "/api/mcp-connections/fuyao"
TOOL = "get_a_share_prices_snapshot"
KLINE = "get_a_share_prices_historical"


class Fuyao:
    def __init__(self):
        self.headers = []
        self.rest_error = 0
        self.before_list = None

    def request(self, request):
        assert request.url.host == "fuyao.aicubes.cn"
        self.headers.append(request.headers["X-api-key"])
        assert "authorization" not in request.headers
        if request.url.path == "/api/a-share/prices/snapshot":
            assert request.url.params["thscodes"] == "600519.SH,000001.SZ"
            return httpx.Response(200, json={"code": self.rest_error, "message": ("没有该接口的访问权限 " if self.rest_error else "") + KEY, "data": {
                "timestamp": 1784275991000, "item": [
                    {"thscode": "000001.SZ", "last_price": 12.5},
                    {"thscode": "600519.SH", "last_price": 1277.8, "prev_price": 1256,
                     "price_change_ratio_pct": 1.735669, "volume": 3098875},
                    {"thscode": "000002.SZ", "last_price": 100},
                ],
            }})
        if request.url.path == "/api/a-share/prices/historical":
            params = request.url.params
            assert params["thscode"] == "600519.SH"
            assert (params["interval"], params["adjust"]) == ("1d", "forward")
            assert int(params["end"]) > int(params["start"]) > 1_000_000_000_000
            return httpx.Response(200, json={"code": 0, "data": {"item": [
                {"date_ms": 1784649600000, "open_price": 10, "high_price": 12,
                 "low_price": 9, "close_price": 11, "volume": 23, "turnover": 1000},
                {"date_ms": 1784563200000, "open_price": 9, "high_price": 11,
                 "low_price": 8, "close_price": 10, "volume": 20},
            ]}})
        assert request.url.path == "/mcp/a-share"
        if request.method == "DELETE":
            assert request.headers["Mcp-Session-Id"] == "fuyao-session"
            return httpx.Response(204)
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}
        else:
            assert request.headers["Mcp-Session-Id"] == "fuyao-session"
            if method == "notifications/initialized":
                return httpx.Response(202)
            if method == "tools/list":
                if self.before_list:
                    self.before_list()
                result = {"tools": [{"name": name, "inputSchema": {"type": "object"}}
                                    for name in (TOOL, "get_meta_tickers_search", "submit_order")]}
            else:
                assert method == "tools/call"
                assert payload["params"] == {"name": TOOL, "arguments": {"thscodes": "600519.SH"}}
                result = {"structuredContent": {"code": 0, "data": {"price": 1277.8}}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result},
                              headers={"mcp-session-id": "fuyao-session"})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fuyao.db'}")
    database.Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add(AppSettings(key=auth.PASSWORD_HASH_KEY, value="configured"))
        db.add(DataSource(id=1, name="行情快照", provider="fuyao", type="fuyao:" + TOOL, enabled=False,
                          config={"params": {"thscodes": "600519.SH,000001.SZ"}}))
        db.commit()
    monkeypatch.setattr(provider_credentials, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(marketdata_client, "_md", None)
    monkeypatch.setattr(auth, "get_jwt_secret", lambda: "fuyao-test-signing-key" * 4)
    upstream = Fuyao()
    transport = httpx.MockTransport(upstream.request)
    monkeypatch.setattr(fuyao, "httpx", SimpleNamespace(HTTPError=httpx.HTTPError,
        Client=lambda **kwargs: httpx.Client(transport=transport, **kwargs)))
    monkeypatch.setattr(fuyao_rest, "http_client", lambda key: httpx.AsyncClient(
        transport=transport, headers={"X-api-key": key}))
    monkeypatch.setattr(mcp_transport, "http_client",
        lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs))
    client = TestClient(app)
    try:
        client.headers["Authorization"] = "Bearer " + auth.create_token()[0]
        yield client, sessions, upstream
    finally:
        client.close()
        engine.dispose()


def test_ftshare_settings_store_credential_separately(setup):
    client, sessions, upstream = setup
    path = "/api/settings/data-providers/ftshare"
    assert client.put(path, headers={"Authorization": ""}, json={"api_key": KEY}).status_code == 401
    assert client.get(path).json()["data"] == {"configured": False, "masked_key": None}
    assert client.put(CREDENTIAL, json={"api_key": KEY}).status_code == 200
    assert client.put("/api/settings/data-providers/unknown", json={"api_key": KEY}).status_code == 404

    invalid = "fixture invalid key"
    rejected = client.put(path, json={"api_key": invalid})
    assert rejected.status_code == 422 and invalid not in rejected.text
    for key, masked in (
        ("ftshare_sk_V.not-a-real-key.Lm10", "ftshare_sk_V****Lm10"),
        ("fixture-ftshare-5678", "fixt****5678"),
        ("short", "****"),
    ):
        response = client.put(path, json={"api_key": f" {key} "})
        expected = {"configured": True, "masked_key": masked}
        assert response.json()["data"] == expected
        latest = client.get(path)
        assert latest.json()["data"] == expected
        assert key not in response.text and key not in latest.text and key not in client.get("/api/settings").text
        with sessions() as db:
            ciphertext = provider_credentials.read(db, "ftshare").encrypted_key
            assert key not in ciphertext
            assert provider_credentials.credential_cipher().decrypt(ciphertext.encode()).decode() == key

    assert client.delete(path).json()["data"] == {"configured": False, "masked_key": None}
    assert client.get(path).json()["data"] == {"configured": False, "masked_key": None}
    with sessions() as db:
        assert fuyao_credentials.decrypt(fuyao_credentials.read(db)) == KEY
    assert not upstream.headers


def test_shared_key_unlocks_rest_and_mcp_and_can_be_replaced_or_removed(setup):
    client, sessions, upstream = setup
    assert client.get(CREDENTIAL).json()["data"] == {"configured": False, "masked_key": None}
    assert client.put("/api/datasources/1", json={"enabled": True}).status_code == 409
    assert client.post(f"{MCP}/a-share/test").status_code == 409
    assert not upstream.headers

    response = client.put(CREDENTIAL, json={"api_key": f" {KEY} "})
    assert response.json()["data"] == {"configured": True, "masked_key": "fixt****-key"}
    assert KEY not in response.text and KEY not in client.get("/api/settings").text
    assert client.put(f"{MCP}/a-share", json={"enabled": True}).status_code == 409
    assert client.put("/api/datasources/1", json={"enabled": True}).status_code == 200
    md = marketdata_client.get_market_data()
    quotes = md.quotes(["600519", "000001"], market="CN")
    assert [(q.symbol, q.current_price, q.source) for q in quotes] == [
        ("600519", 1277.8, "fuyao"), ("000001", 12.5, "fuyao"),
    ]
    assert quotes[0].quote_date.isoformat() == "2026-07-17"
    assert quotes[0].change_pct == 1.735669 and quotes[0].volume == 3098875
    result = client.post("/api/datasources/1/test").json()["data"]
    assert result["test_passed"] and len(json.loads(result["raw_response"])["data"]["item"]) == 3

    checked = client.post(f"{MCP}/a-share/test").json()["data"]
    assert len(checked["services"]) == 8
    a_share = next(service for service in checked["services"] if service["id"] == "a-share")
    assert [tool["name"] for tool in a_share["tools"]] == [TOOL]
    assert client.put(f"{MCP}/a-share", json={"enabled": True}).status_code == 200
    with sessions() as db:
        assert KEY not in fuyao_credentials.read(db).encrypted_key
        registry = ToolRegistry()
        register_fuyao_tools(registry, db, "zh-CN")
    result = asyncio.run(registry.execute("fuyao_a_share_prices_snapshot", None, {"thscodes": "600519.SH"}))
    assert result.ok and json.loads(result.summary)["data"]["price"] == 1277.8
    assert all(value == KEY for value in upstream.headers)
    assert KEY not in client.get(MCP).text and KEY not in client.get("/api/datasources/1").text

    count = len(upstream.headers)
    client.put("/api/datasources/1", json={"enabled": False}).raise_for_status()
    paused_tool = asyncio.run(registry.execute("fuyao_a_share_prices_snapshot", None, {"thscodes": "600519.SH"}))
    assert paused_tool.error_code == "datasource_operation_disabled" and len(upstream.headers) == count
    client.put("/api/datasources/1", json={"enabled": True}).raise_for_status()

    client.put(CREDENTIAL, json={"api_key": ROTATED}).raise_for_status()
    assert not next(service for service in client.get(MCP).json()["data"]["services"]
                    if service["id"] == "a-share")["enabled"]
    assert not asyncio.run(registry.execute("fuyao_a_share_prices_snapshot", None, {})).ok
    assert client.post("/api/datasources/1/test").json()["data"]["test_passed"]
    assert upstream.headers[-1] == ROTATED
    assert client.delete(CREDENTIAL).json()["data"] == {"configured": False, "masked_key": None}
    assert marketdata_client.DbConfigProvider().sources_for("quote", "CN") == []


def test_daily_kline_and_safe_rest_errors(setup):
    client, sessions, upstream = setup
    seed_business(sessions)
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    response = client.post("/api/datasources", json={
        "name": "Fuyao K", "provider": "fuyao", "type": "kline", "enabled": True,
    })
    assert response.status_code == 422
    quote = f"/api/datasources/{row_id(sessions, TOOL)}"
    assert client.put(quote, json={"config": {"params": {"api_key": "must-not-be-stored"}}}).status_code == 422
    client.put(quote, json={"enabled": True}).raise_for_status()
    client.put(f"/api/datasources/{row_id(sessions, KLINE)}", json={"enabled": True}).raise_for_status()
    bars = marketdata_client.get_market_data().klines("600519", market="CN", days=1)
    assert [(bar.date, bar.close, bar.turnover) for bar in bars] == [("2026-07-22", 11.0, 1000)]
    upstream.rest_error = 2003
    result = client.post("/api/datasources/1/test")
    assert not result.json()["data"]["test_passed"]
    assert "没有该接口的访问权限" in json.loads(result.json()["data"]["raw_response"])["message"]
    assert KEY not in result.text


def test_requires_login_and_cannot_enable_a_probe_for_an_old_key(setup):
    client, sessions, upstream = setup
    authorization = client.headers.pop("Authorization")
    assert client.put(CREDENTIAL, json={"api_key": KEY}).status_code == 401
    assert client.get(MCP).status_code == 401
    client.headers["Authorization"] = authorization
    response = client.put(CREDENTIAL, json={"api_key": {"private": KEY}})
    assert response.status_code == 422 and KEY not in response.text
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    assert client.post(f"{MCP}/other-host/test").status_code == 404

    def rotate():
        with sessions() as db:
            provider_credentials.replace(db, "fuyao", ROTATED)

    upstream.before_list = rotate
    assert client.post(f"{MCP}/a-share/test").status_code == 409
    assert client.put(f"{MCP}/a-share", json={"enabled": True}).status_code == 409


REST = "/api/datasources/fuyao"


def test_every_catalog_operation_dispatches_to_its_official_get_path(setup, monkeypatch):
    client, sessions, _ = setup
    seed_business(sessions)
    assert client.get(REST + "/catalog").json()["data"]["configured"] is False
    assert client.post(REST + f"/query/{TOOL}", json={}).status_code == 409
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    assert client.post(REST + f"/query/{TOOL}", json={}).json()["error_code"] == "datasource_operation_disabled"
    for source in client.get("/api/datasources").json()["data"]:
        if source["provider"] == "fuyao":
            client.put(f"/api/datasources/{source['id']}", json={"enabled": True}).raise_for_status()

    requests = []

    def remote(request):
        assert request.url.host == "fuyao.aicubes.cn"
        assert request.method == "GET"
        assert request.headers["X-api-key"] == KEY
        requests.append(request)
        return httpx.Response(200, text='{"code":0,"request_id":"test","data":{"id":9223372036854775807}}')

    monkeypatch.setattr(fuyao_rest, "http_client", lambda key: httpx.AsyncClient(
        transport=httpx.MockTransport(remote), headers={"X-api-key": key}, follow_redirects=False))
    catalog = client.get(REST + "/catalog").json()["data"]
    assert catalog["configured"] is True
    operations = catalog["operations"]
    assert len(set(item["id"] for item in operations)) == len(set(item["path"] for item in operations)) == 111
    assert {item["group"] for item in operations} == {
        "a-share", "a-share-index", "fund", "futures", "options", "hk-share", "meta", "news",
    }
    for operation in operations:
        params = {p["name"]: p["example"] for p in operation["parameters"] if "example" in p}
        response = client.post(REST + "/query/" + operation["id"], json={"params": params})
        assert response.status_code == 200, (operation["id"], response.text)
        result = response.json()["data"]
        assert result["business_code"] == 0 and "9223372036854775807" in result["response_json"]
        assert requests[-1].url.path == operation["path"]
        assert dict(requests[-1].url.params) == {
            name: str(value).lower() if type(value) is bool else str(value) for name, value in params.items()
        }
    assert len(requests) == 111
    client.put("/api/datasources/providers/fuyao", json={"enabled": False}).raise_for_status()
    assert client.get(REST + "/catalog").json()["data"]["paused"] is True
    assert client.post(REST + f"/query/{TOOL}", json={}).status_code == 409
    assert len(requests) == 111


def test_rest_gateway_rejects_unlisted_requests_and_preserves_provider_errors(setup, monkeypatch):
    client, sessions, _ = setup
    seed_business(sessions)
    auth_header = client.headers.pop("Authorization")
    assert client.get(REST + "/catalog").status_code == 401
    assert client.post(REST + f"/query/{TOOL}", json={}).status_code == 401
    client.headers["Authorization"] = auth_header
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    for source in client.get("/api/datasources").json()["data"]:
        if source["provider"] == "fuyao" and source["type"] in {"fuyao:" + TOOL, "fuyao:get_meta_tickers_search"}:
            client.put(f"/api/datasources/{source['id']}", json={"enabled": True}).raise_for_status()

    attempts = []

    def remote(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(200, json={"code": 2003, "message": KEY, "request_id": "limited"})
        return httpx.Response(302, headers={"location": "https://elsewhere.invalid/"})

    monkeypatch.setattr(fuyao_rest, "http_client", lambda key: httpx.AsyncClient(
        transport=httpx.MockTransport(remote), headers={"X-api-key": key}, follow_redirects=False))
    assert client.post(REST + "/query/get_unknown", json={}).status_code == 404
    assert client.post(REST + f"/query/{TOOL}", json={"url": "https://elsewhere.invalid"}).status_code == 422
    assert client.post(REST + f"/query/{TOOL}", json={"params": {"api_key": "override"}}).status_code == 422
    assert client.post(REST + "/query/get_meta_tickers_search", json={}).status_code == 422
    assert client.post(REST + "/query/get_meta_tickers_search", json={"params": {"q": "600519", "limit": "NaN"}}).status_code == 422
    assert not attempts
    response = client.post(REST + f"/query/{TOOL}", json={"params": {"thscodes": "600519.SH"}})
    result = response.json()["data"]
    assert result["business_code"] == 2003 and result["request_id"] == "limited"
    assert KEY not in response.text
    assert client.post(REST + f"/query/{TOOL}", json={}).status_code == 502
    assert [request.url.host for request in attempts] == ["fuyao.aicubes.cn", "fuyao.aicubes.cn"]


def seed_business(sessions):
    from server import reconcile_data_sources
    with sessions() as db:
        reconcile_data_sources(db)


def row_id(sessions, operation):
    with sessions() as db:
        return db.scalar(select(DataSource.id).where(DataSource.provider == "fuyao", DataSource.type == "fuyao:" + operation))


def test_operation_migration_copies_switches_without_overwriting_item_settings():
    from src.platform.persistence.migrations import _m149_fuyao_operation_settings

    engine = create_engine("sqlite://")
    database.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            DataSource(name="Old fundamentals", provider="fuyao", type="fundamentals", enabled=True),
            DataSource(name="Old auction", provider="fuyao", type="auction", enabled=False),
            DataSource(name="Saved valuation", provider="fuyao", type="fuyao:get_a_share_valuations_snapshot",
                       enabled=False, config={"params": {"thscodes": "600519.SH"}}),
            DataSource(name="Legacy northbound", provider="ths", type="northbound", enabled=True),
        ])
        db.commit()
    with engine.begin() as conn:
        _m149_fuyao_operation_settings(conn)
        _m149_fuyao_operation_settings(conn)
    with Session(engine) as db:
        rows = db.scalars(select(DataSource)).all()
        by_type = {row.type: row for row in rows}
        assert len(by_type) == len(rows)
        assert by_type["fuyao:get_a_share_financials_balance_sheets"].enabled
        assert not by_type["fuyao:get_a_share_auction_snapshot"].enabled
        saved = by_type["fuyao:get_a_share_valuations_snapshot"]
        assert not saved.enabled and saved.config == {"params": {"thscodes": "600519.SH"}}
        assert {"fundamentals", "auction"}.isdisjoint(by_type)
        assert by_type["northbound"].enabled
    engine.dispose()


def test_saved_parameters_drive_only_the_selected_operation_test(setup, monkeypatch):
    client, sessions, _ = setup
    seed_business(sessions)
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    sent = []

    def remote(request):
        sent.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"code": 0, "data": {"item": []}})

    monkeypatch.setattr(fuyao_rest, "http_client", lambda key: httpx.AsyncClient(
        transport=httpx.MockTransport(remote), headers={"X-api-key": key}))
    path = f"/api/datasources/{row_id(sessions, TOOL)}"
    settings = {"params": {"thscodes": "000333.SZ"}}
    client.put(path, json={"config": settings}).raise_for_status()
    assert client.post(path + "/test").status_code == 409
    assert not sent
    client.put(path, json={"enabled": True}).raise_for_status()
    result = client.post(path + "/test").json()["data"]
    assert result["test_passed"] and json.loads(result["raw_response"]) == {"code": 0, "data": {"item": []}}
    assert sent == [("/api/a-share/prices/snapshot", settings["params"])]
    catalog = client.get(REST + "/catalog").json()["data"]["operations"]
    own = next(op for op in catalog if op["id"] == TOOL)
    assert own["enabled"] and own["settings"] == settings


def test_all_111_operations_have_independent_source_switches(setup, monkeypatch):
    client, sessions, _ = setup
    seed_business(sessions)
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    sources = [x for x in client.get("/api/datasources").json()["data"] if x["provider"] == "fuyao"]
    assert len(sources) == 111
    assert {s["fuyao_operation"]["id"] for s in sources} == set(fuyao_rest.OPERATIONS)
    assert all(not x["enabled"] and not x["is_orphan"] for x in sources)

    def registry():
        with sessions() as db:
            result = ToolRegistry()
            register_fuyao_rest_tools(result, db, "zh-CN")
            return result

    assert not registry().registered_tools()
    for source in sources:
        client.put(f"/api/datasources/{source['id']}", json={"enabled": True}).raise_for_status()
    registered = registry()
    assert {s.name for s in registered.registered_tools()} == {
        "fuyao_rest_" + _tool_name(op) for op in fuyao_rest.OPERATIONS
    }
    requests = []

    def remote(request):
        assert request.headers["X-api-key"] == KEY
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": [{"variety": "铜"}]})

    monkeypatch.setattr(fuyao_rest, "http_client", lambda key: httpx.AsyncClient(
        transport=httpx.MockTransport(remote), headers={"X-api-key": key}))
    name = "fuyao_rest_futures_varieties_list"
    result = asyncio.run(registered.execute(name, None, {}))
    assert result.ok and "铜" in result.summary
    assert json.loads(result.data["response_json"]) == {"code": 0, "data": [{"variety": "铜"}]}
    assert requests[-1].url.path == "/api/futures/varieties/list"
    future_source = next(row for row in sources if row["type"] == "fuyao:get_futures_varieties_list")
    client.put(f"/api/datasources/{future_source['id']}", json={"enabled": False}).raise_for_status()
    remaining = {tool.name for tool in registry().registered_tools()}
    assert name not in remaining
    assert len(remaining) == 110
    assert any(tool != name and tool.startswith("fuyao_rest_futures_") for tool in remaining)
    assert not asyncio.run(registered.execute(name, None, {})).ok
    assert len(requests) == 1  # An already-running assistant cannot bypass the switch.


def test_stock_search_selects_an_independent_provider_before_request(setup, monkeypatch):
    client, sessions, _ = setup
    seed_business(sessions)
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    rows = client.get("/api/datasources?type=stock_search").json()["data"]
    ids = {row["provider"]: row["id"] for row in rows}
    client.put(f"/api/datasources/{row_id(sessions, 'get_meta_tickers_search')}", json={"enabled": True}).raise_for_status()
    attempts = []
    should_fail = False

    def remote(request):
        assert request.url.path == "/api/meta/tickers/search"
        assert request.url.params["q"] == "600519"
        attempts.append(request)
        if should_fail:
            return httpx.Response(200, json={"code": 2003, "data": None})
        return httpx.Response(200, json={"code": 0, "data": {"item": [{
            "ticker": "600519", "name": "同花顺名称", "exchange": "SH", "asset_type": "a-share",
        }]}})

    monkeypatch.setattr(fuyao_rest, "http_client", lambda key: httpx.AsyncClient(
        transport=httpx.MockTransport(remote), headers={"X-api-key": key}))
    monkeypatch.setattr(stock_list, "_public_search_stocks",
                        lambda *_: [{"symbol": "600519", "name": "公共来源", "market": "CN"}])

    def business():
        return client.get("/api/stocks/search", params={"q": "600519", "market": "CN"}).json()["data"]

    assert business()[0]["name"] == "公共来源" and not attempts
    assert client.post(f"/api/datasources/{ids['eastmoney']}/move", json={"direction": -1}).status_code == 409
    client.put("/api/datasources/providers/eastmoney", json={"enabled": False}).raise_for_status()
    assert business()[0]["name"] == "同花顺名称" and len(attempts) == 1
    should_fail = True
    assert business() == [] and len(attempts) == 2


def test_native_research_routes_cover_the_eight_remaining_businesses(setup, monkeypatch):
    from src.modules.market.research_workspaces import WORKSPACES

    client, sessions, _ = setup
    seed_business(sessions)
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    rows = {r["fuyao_operation"]["id"]: r for r in client.get("/api/datasources").json()["data"] if r["provider"] == "fuyao"}
    assert set(WORKSPACES) == fuyao_business.WORKSPACE_CAPABILITIES
    assert sum(len(views) for views in WORKSPACES.values()) == 64
    for kind, views in WORKSPACES.items():
        assert {view.operation for view in views} == set(fuyao_business.BY_CAPABILITY[kind])
        for view in views:
            assert rows[view.operation]["workspace_path"] == f"/market-data/{kind}"
            assert rows[view.operation]["engine_attached"]

    requests = []

    def remote(request):
        assert request.headers["X-api-key"] == KEY
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {"item": [{"name": "业务样本"}]}})

    monkeypatch.setattr(fuyao_rest, "http_client", lambda key: httpx.AsyncClient(
        transport=httpx.MockTransport(remote), headers={"X-api-key": key}))
    base = "/api/research-data"
    assert client.post(f"{base}/index_constituents/directory", json={}).status_code == 409
    assert not requests
    for kind, views in WORKSPACES.items():
        for view in views:
            client.put(f"/api/datasources/{rows[view.operation]['id']}", json={"enabled": True}).raise_for_status()
        workspace = client.get(f"{base}/{kind}").json()["data"]
        assert len(workspace["views"]) == len(views)
        assert workspace["sources"][0]["enabled"]
        assert "get_" not in str([v["id"] for v in workspace["views"]])
        for view in views:
            operation = fuyao_rest.OPERATIONS[view.operation]
            filters = {p["name"]: p["example"] for p in operation["parameters"] if "example" in p}
            payload = {"filters": filters}
            if view.id == "strategy":
                payload["conditions"] = {verb: [json.loads(filters.pop(f"{verb}_conditions"))] for verb in ("buy", "sell")}
            response = client.post(f"{base}/{kind}/{view.id}", json=payload)
            assert response.status_code == 200, (view.id, response.text)
            assert response.json()["data"]["result"]["item"][0]["name"] == "业务样本"
            assert requests[-1].url.path == operation["path"]
            if view.id == "strategy":
                assert json.loads(requests[-1].url.params["buy_conditions"])["indicator_code"] == "rsi_pct"
    assert len(requests) == 64
    filings = next(view for view in WORKSPACES["ipo"] if view.id == "filings")
    client.put(f"/api/datasources/{rows[filings.operation]['id']}", json={"enabled": False}).raise_for_status()
    assert client.get(f"{base}/ipo").json()["data"]["sources"][0]["enabled"]
    assert client.post(f"{base}/ipo/filings", json={}).status_code == 409
    assert len(requests) == 64


def test_research_uses_one_independent_provider_per_request(setup, monkeypatch):
    from src.modules.market.api import research_data
    from src.modules.market.research_workspaces import WORKSPACES

    client, sessions, _ = setup
    seed_business(sessions)
    client.put(CREDENTIAL, json={"api_key": KEY}).raise_for_status()
    calls = []
    first_fails = False

    async def fuyao(operation, args, **kwargs):
        calls.append("fuyao")
        if first_fails:
            raise RuntimeError("Provider unavailable")
        return {"item": []}  # A legitimately empty IPO calendar is a success.

    async def backup(operation, args, **kwargs):
        calls.append("eastmoney")
        return {"item": [{"company_name": "备选"}]}

    monkeypatch.setattr(research_data, "PROVIDERS", {"fuyao": fuyao, "eastmoney": backup})
    with sessions() as db:
        filings = next(view for view in WORKSPACES["ipo"] if view.id == "filings")
        preferred = db.scalar(select(DataSource).where(DataSource.type == "fuyao:" + filings.operation,
                                                       DataSource.provider == "fuyao"))
        preferred.enabled = True
        alternate = DataSource(type="ipo", provider="eastmoney", name="备用来源", priority=2, enabled=True)
        db.add(alternate)
        db.commit()
        alternate_id = alternate.id
    path = "/api/research-data/ipo/filings"
    assert client.post(path, json={}).json()["data"]["provider"] == "fuyao" and calls == ["fuyao"]
    first_fails = True
    assert client.post(path, json={}).status_code == 502
    assert calls == ["fuyao", "fuyao"]
    assert client.post(f"/api/datasources/{alternate_id}/move", json={"direction": -1}).status_code == 409
    client.put("/api/datasources/providers/fuyao", json={"enabled": False}).raise_for_status()
    assert client.post(path, json={}).json()["data"]["provider"] == "eastmoney"
    assert calls[-1] == "eastmoney"
