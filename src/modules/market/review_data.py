"""Independent market data adapter; no user credentials or arbitrary URLs.

Keep provider timestamps and partial errors intact. A bounded, coalesced cache
limits upstream traffic and only serves explicitly marked stale data on failure.
"""
import asyncio
import copy
import time
from collections import OrderedDict
from datetime import datetime, timezone

import httpx

from src.modules.market import review_sources

RESOURCES = {"board": 30, "dates": 300, "overseas": 60, "daily": 300, "etf": 60}
MAX_ENTRIES = 96
STALE_SECONDS = 86400
_cache: OrderedDict[tuple, tuple[float, str, object]] = OrderedDict()
_inflight: dict[tuple, asyncio.Task] = {}
_retry_after: dict[tuple, float] = {}


def _validate(resource: str, value: object) -> None:
    if resource == "dates":
        if not isinstance(value, list) or not all(isinstance(d, str) and len(d) == 10 for d in value):
            raise ValueError("Invalid trading dates")
        return
    if not isinstance(value, dict):
        raise ValueError("Invalid market payload")
    required = {"board": ("date", "stocks", "active_count", "opened_count"),
                "overseas": ("industry", "indicators"), "daily": ("lhb", "futures"),
                "etf": ("date", "minutes")}[resource]
    if not all(key in value for key in required):
        raise ValueError("Incomplete market payload")
    if resource == "board" and not isinstance(value["stocks"], list):
        raise ValueError("Invalid stock pool")


async def _fetch(resource: str, date: str | None) -> object:
    value = await review_sources.fetch(resource, date)
    if not resource.startswith("minute/"):
        _validate(resource, value)
    if resource == "board" and date and value["date"] != date:
        raise ValueError("Upstream returned a different trading date")
    return value


async def _refresh(key: tuple, resource: str, date: str | None) -> tuple:
    try:
        value = await _fetch(resource, date)
        entry = (time.monotonic(), datetime.now(timezone.utc).isoformat(), value)
        _cache[key] = entry
        _cache.move_to_end(key)
        _retry_after.pop(key, None)
        while len(_cache) > MAX_ENTRIES:
            removed, _ = _cache.popitem(last=False)
            _retry_after.pop(removed, None)
        return entry
    finally:
        _inflight.pop(key, None)


async def load_review(resource: str, date: str | None = None) -> dict:
    key = (resource, date)
    now = time.monotonic()
    cached = _cache.get(key)
    ttl = 60 if resource.startswith("minute/") and date == review_sources.now().date().isoformat() else 300 if date else RESOURCES.get(resource, 30)
    stale = False
    error = None
    if cached and now - cached[0] < ttl:
        entry = cached
    elif cached and now < _retry_after.get(key, 0):
        entry, stale, error = cached, True, "upstream_unavailable"
    else:
        try:
            task = _inflight.get(key)
            if task is None:
                task = asyncio.create_task(_refresh(key, resource, date))
                _inflight[key] = task
            entry = await asyncio.shield(task)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
            if not cached or now - cached[0] > STALE_SECONDS:
                raise ReviewUnavailable() from None
            entry, stale, error = cached, True, "upstream_unavailable"
            _retry_after[key] = now + 30
    payload = copy.deepcopy(entry[2])
    sources = payload.get("sources", []) if isinstance(payload, dict) else [review_sources.PROVIDERS["sina"], review_sources.PROVIDERS["tencent"]]
    return {"payload": payload, "source": "+".join(s["id"] for s in sources) or "independent",
            "source_url": sources[0]["url"] if sources else "", "sources": sources,
            "fetched_at": entry[1], "stale": stale, "error": error}



class ReviewUnavailable(Exception):
    pass
