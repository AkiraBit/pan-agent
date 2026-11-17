import json
from collections import Counter

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import reconcile_data_sources
from src.bootstrap.application import app
from src.modules.administration.api import auth
from src.platform.marketdata import provider_credentials, tushare_rest
from src.platform.persistence import database
from src.platform.persistence.models import AppSettings, DataSource

BASE = "/api/datasources/tushare"
KEY = "not-a-real-tushare-credential"


def test_catalog_covers_the_three_document_sections_in_official_order():
    operations = tushare_rest.CATALOG["operations"]
    assert len({op["id"] for op in operations}) == len(operations)
    assert Counter(op["group"] for op in operations) == {"股票数据": 106, "ETF专题": 18, "指数专题": 24}
    assert list(dict.fromkeys(op["subgroup"] for op in operations if op["group"] == "股票数据")) == [
        "基础数据", "行情数据", "财务数据", "参考数据", "特色数据",
        "两融及转融通", "资金流向数据", "打板专题数据",
    ]
    assert all("subgroup" not in op for op in operations if op["group"] != "股票数据")
    assert "pro_bar" not in tushare_rest.OPERATIONS
    for op in operations:
        tushare_rest.validate(op, {})


def test_tushare_uses_saved_key_and_honors_endpoint_and_provider_switches(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    database.Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add(AppSettings(key=auth.PASSWORD_HASH_KEY, value="configured"))
        reconcile_data_sources(db)
        reconcile_data_sources(db)
        assert db.query(DataSource).filter_by(provider="tushare").count() == 148
        source_id = db.query(DataSource).filter_by(provider="tushare", type="tushare:fund_daily").one().id
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(provider_credentials, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(auth, "get_jwt_secret", lambda: "isolated-tushare-test-signing-key" * 2)

    calls = []
    status = 0

    def relay(request):
        assert request.method == "POST"
        assert str(request.url) == tushare_rest.RELAY
        calls.append(json.loads(request.content))
        if status:
            return httpx.Response(200, json={"code": status, "msg": f"API error for {KEY}", "data": None})
        return httpx.Response(200, json={"code": 0, "data": {"fields": ["close"], "items": [[4.2]]}})

    monkeypatch.setattr(tushare_rest, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(relay)))
    invoke = BASE + "/query/fund_daily"
    source_path = f"/api/datasources/{source_id}"
    key_path = "/api/settings/data-providers/tushare"
    config = {"params": {"ts_code": "510300.SH", "trade_date": "20251031"}, "fields": "close"}
    with TestClient(app) as client:
        assert client.get(BASE + "/catalog").status_code == 401
        client.headers["Authorization"] = "Bearer " + auth.create_token()[0]
        assert client.post(invoke, json=config).status_code == 409
        pasted = f" \ufeffpro = ts.pro_api(‘{KEY[:4]}\u200b{KEY[4:]}’) "
        for value in (KEY, f'"{KEY}"', pasted):
            credential = client.put(key_path, json={"api_key": value})
            assert credential.json()["data"] == {"configured": True, "masked_key": "not-****tial"}
        with sessions() as db:
            assert KEY not in provider_credentials.read(db, "tushare").encrypted_key
        for invalid in (f"pro = ts.pro_api({KEY})", tushare_rest.RELAY, "two separate words"):
            response = client.put(key_path, json={"api_key": invalid})
            assert response.status_code == 422
            assert response.json()["error_code"] == "tushare_key_format_invalid"
            assert invalid not in response.text
        assert client.put(source_path, json={"config": {"params": {"token": "custom"}}}).status_code == 422
        assert client.post(invoke, json={**config, "url": "https://example.com"}).status_code == 422
        assert client.post(BASE + "/query/fut_daily", json={"params": {}}).status_code == 404
        assert not calls

        updated = client.put(source_path, json={"config": config}).json()["data"]
        assert updated["config"] == config
        assert updated["connection_status"] == "ready"
        assert updated["routing"]["mode"] == "direct"
        result = client.post(source_path + "/test").json()["data"]
        assert result["test_passed"] and result["count"] == 1
        assert calls == [{"api_name": "fund_daily", "token": KEY, **config}]

        status = 40301
        response = client.post(source_path + "/test")
        assert not response.json()["data"]["test_passed"]
        assert response.json()["data"]["business_code"] == 40301
        assert KEY not in response.text and "[redacted]" in response.text
        assert client.put(source_path, json={"enabled": False}).status_code == 200
        assert client.post(invoke, json=config).status_code == 409
        bulk = client.put("/api/datasources/providers/tushare/endpoints", json={"enabled": True})
        assert len(bulk.json()["data"]["source_ids"]) == 148
        assert client.put("/api/datasources/providers/tushare", json={"enabled": False}).status_code == 200
        assert client.post(source_path + "/test").status_code == 409
        assert client.post(invoke, json=config).status_code == 409
        assert client.delete(key_path).json()["data"]["configured"] is False
        assert len(calls) == 2
    engine.dispose()
