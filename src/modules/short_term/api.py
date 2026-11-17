"""Authenticated on-demand collection. Reads never initiate upstream traffic."""
import asyncio
import json
import logging
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, time as wall_time
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from marketdata.short_term import POOLS, TZ, quotes
from .market_sources import limit_pool

from src.modules.short_term.analysis import analyze, phase_at, reference_day
from src.modules.short_term.speculation import candidate_concepts, relay_observation, theme_observation, trend_candidates, trend_structure
from src.platform.marketdata.marketdata_client import get_market_data
from src.platform.persistence.database import SessionLocal
from src.platform.persistence.models import ShortTermSnapshot

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="short-term")
_lock = threading.Lock()
_future = None
_started = 0.0
_error = None


def completed_day(now):
    # Intraday partial bars must not be compared with completed daily bars.
    return reference_day(now.replace(hour=9, minute=0)) if now.time() < wall_time(15) else reference_day(now)


def trend_bars(code):
    try:
        return [asdict(b) for b in get_market_data().klines(code, market="CN", days=40, min_count=25)]
    except Exception:
        logging.getLogger(__name__).warning("Short-term daily bars unavailable for %s", code)
        return []


def collect():
    global _error
    try:
        now = datetime.now(TZ)
        day = reference_day(now)
        if day is None or phase_at(now) == "unknown":
            raise ValueError("calendar_unknown")
        with ThreadPoolExecutor(max_workers=4) as executor:
            market_job = executor.submit(quotes)
            concepts_job = executor.submit(quotes, "concepts", "m:90+t:3")
            pool_jobs = {k: executor.submit(limit_pool, k, day) for k in POOLS}
            market, concepts = market_job.result(), concepts_job.result()
            pools = {k: job.result() for k, job in pool_jobs.items()}
            top = candidate_concepts(concepts)
            member_jobs = [(r, executor.submit(quotes, f"theme:{r['code']}", f"b:{r['code']}")) for r in top]
            members = [(r, job.result()) for r, job in member_jobs]
            trend_stocks = trend_candidates(market, members)
            bars = dict(zip([r["code"] for r in trend_stocks], executor.map(trend_bars, [r["code"] for r in trend_stocks])))
        now = datetime.now(TZ)
        payload = analyze(market, concepts, members, pools, now, day)
        payload.update(version=2, speculation={"relay": relay_observation(pools),
            "themes": theme_observation(market, concepts, members, pools),
            "trends": [{**r, "structure": trend_structure(bars[r["code"]], completed_day(now))} for r in trend_stocks]})
        raw = {"market": market.rows, "concepts": concepts.rows,
               "members": {r["code"]: b.rows for r, b in members},
               "pools": {k: b.rows for k, b in pools.items()}, "trend_bars": bars}
        with SessionLocal() as db:
            db.add(ShortTermSnapshot(captured_at=now.astimezone(timezone.utc).isoformat(), payload=payload,
                                    evidence=zlib.compress(json.dumps(raw).encode())))
            cutoff = (now - timedelta(days=14)).astimezone(timezone.utc).isoformat()
            db.query(ShortTermSnapshot).filter(ShortTermSnapshot.captured_at < cutoff).delete()
            db.commit()
    except Exception:
        _error = "collection_failed"
        logging.getLogger(__name__).exception("Short-term observation collection failed")


@router.post("/refresh", status_code=202)
def refresh():
    global _future, _started, _error
    with _lock:
        if _future is not None and not _future.done():
            return {"state": "collecting"}
        remaining = max(0, 300 - (time.monotonic() - _started))
        if remaining:
            return {"state": "cooldown", "retry_after": round(remaining)}
        _started, _error = time.monotonic(), None
        _future = _executor.submit(collect)
        return {"state": "collecting"}


@router.get("/overview")
def overview(snapshot_id: int | None = Query(None, ge=1)):
    with SessionLocal() as db:
        query = db.query(ShortTermSnapshot)
        row = query.filter_by(id=snapshot_id).first() if snapshot_id else query.order_by(ShortTermSnapshot.id.desc()).first()
        if snapshot_id and row is None:
            raise HTTPException(404, "Snapshot not found")
        history = db.query(ShortTermSnapshot.id, ShortTermSnapshot.captured_at).order_by(ShortTermSnapshot.id.desc()).limit(30).all()
        now = datetime.now(TZ)
        return {"snapshot": {**row.payload, "id": row.id} if row else None,
                "phase": phase_at(now), "server_time": now.isoformat(),
                "collecting": _future is not None and not _future.done(), "error": _error,
                "retry_after": max(0, round(300 - (time.monotonic() - _started))),
                "history": [{"id": h.id, "captured_at": h.captured_at} for h in history]}


async def shutdown():
    await asyncio.to_thread(_executor.shutdown, wait=True, cancel_futures=True)
