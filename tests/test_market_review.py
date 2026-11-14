import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.modules.market import review_data as data
from src.modules.market.api.review import router


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_review_cache():
    data._cache.clear()
    data._inflight.clear()
    data._retry_after.clear()
    yield
    data._cache.clear()


@pytest.mark.anyio
async def test_concurrent_requests_share_upstream_and_cached_payload_is_not_mutable(monkeypatch):
    async def fetch(*args):
        await asyncio.sleep(.01)
        return {"date": "2026-11-12", "stocks": [{"code": "603366"}]}
    mock = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(data, "_fetch", mock)
    values = await asyncio.gather(*(data.load_review("board") for _ in range(8)))
    assert mock.await_count == 1
    values[0]["payload"]["stocks"].clear()
    assert (await data.load_review("board"))["payload"]["stocks"]
    assert not values[0]["stale"]
    assert values[0]["source"] == "independent"


@pytest.mark.anyio
async def test_history_has_separate_cache_and_stale_data_is_marked(monkeypatch):
    monkeypatch.setattr(data, "_fetch", AsyncMock(return_value={"date": "2026-11-11"}))
    result = await data.load_review("board", "2026-11-11")
    key = ("board", "2026-11-11")
    data._cache[key] = (time.monotonic() - 301, result["fetched_at"], result["payload"])
    mock = AsyncMock(side_effect=httpx.ConnectError("offline"))
    monkeypatch.setattr(data, "_fetch", mock)
    stale = await data.load_review(*key)
    assert stale["stale"] and stale["error"] == "upstream_unavailable"
    assert stale["fetched_at"] == result["fetched_at"]
    assert stale["payload"]["date"] == "2026-11-11"
    await data.load_review(*key)
    assert mock.await_count == 1  # failure backoff
    with pytest.raises(data.ReviewUnavailable):
        await data.load_review("board", "2026-11-12")


@pytest.mark.anyio
async def test_expired_cache_is_not_presented_as_current(monkeypatch):
    data._cache[("board", None)] = (time.monotonic() - 86401, "old", {})
    monkeypatch.setattr(data, "_fetch", AsyncMock(side_effect=ValueError("bad schema")))
    with pytest.raises(data.ReviewUnavailable):
        await data.load_review("board")


@pytest.mark.anyio
async def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(data, "_fetch", AsyncMock(return_value={}))
    for i in range(data.MAX_ENTRIES + 3):
        await data.load_review("board", str(i))
    assert len(data._cache) == data.MAX_ENTRIES
    assert ("board", "0") not in data._cache


@pytest.mark.anyio
async def test_wrong_history_date_is_rejected(monkeypatch):
    monkeypatch.setattr(data.review_sources, "fetch", AsyncMock(return_value={"date": "2026-11-12", "stocks": [], "active_count": 0, "opened_count": 0}))
    with pytest.raises(ValueError, match="different trading date"):
        await data._fetch("board", "2026-11-11")


@pytest.mark.parametrize("resource,payload", [("board", []), ("board", {"stocks": []}), ("dates", [7]), ("etf", {"date": "2026-11-12"})])
def test_invalid_upstream_schema_is_rejected(resource, payload):
    with pytest.raises(ValueError):
        data._validate(resource, payload)


def test_api_rejects_arbitrary_resource_bad_date_and_unsupported_history(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/anything').status_code == 422
        assert client.get('/board?date=2026-99-99').status_code == 422
        assert client.get('/etf?date=2026-11-11').status_code == 422
        assert client.get('/minute/abc?date=2026-11-11').status_code == 422
        assert client.get('/minute/600000').status_code == 422
        monkeypatch.setattr('src.modules.market.api.review.load_review', AsyncMock(side_effect=data.ReviewUnavailable()))
        assert client.get('/board').status_code == 503
