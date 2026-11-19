"""Authenticated Tushare intraday read, backed by the per-session database."""
import asyncio
from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, Query

from src.modules.market.etf import breadth_replay, intraday, market_stats, prices, linked
from src.web.errors import api_error

router = APIRouter()


@router.get("/analysis")
async def linked_analysis(date: Date):
    _check_date(date)
    return await linked.load(date)


@router.get("/components")
async def component_analysis(date: Date, group: str = Query(pattern=r"^(csi300|sse50|csi500|csi1000|growth|star|a500|sse)$"),
                             minute: str = Query(pattern=r"^\d{2}:\d{2}$")):
    _check_date(date)
    through = market_stats.latest_closed_minute(date, intraday.now_cn())
    if minute not in intraday.MINUTE_SET or through is None or minute > through:
        raise api_error(422, "etf_invalid_minute", "请选择已结束的交易分钟。")
    return {**(await linked.components(date, group, minute)), "backfill": await linked.replay.status(date, group)}


@router.post("/components/backfill")
async def backfill_components(date: Date, group: str = Query(pattern=r"^(all|csi300|sse50|csi500|csi1000|growth|star|a500|sse)$")):
    _check_date(date)
    try:
        status = await linked.replay.start(date, group)
    except intraday.TushareFailure as exc:
        return {"status": "unavailable", "reason": exc.code}
    return {"status": status}


def _check_date(day: Date):
    if not intraday.FIRST_DATE <= day <= intraday.now_cn().date():
        raise api_error(422, "etf_invalid_date", "请选择有效的交易日期。")


@router.get("/intraday")
async def intraday_session(date: Date | None = None, refresh: bool = False):
    if date:
        _check_date(date)
    payload = await intraday.store.load(date, refresh=refresh)
    return {**payload, "market": intraday.market_clock()}


@router.get("/turnover-baseline")
async def turnover_baseline(date: Date):
    _check_date(date)
    return await intraday.store.turnover_baseline(date)


@router.get("/market-stats")
async def session_market_stats(date: Date | None = None):
    if date:
        _check_date(date)
    now = intraday.now_cn()
    day = date or intraday.latest_session(now)
    # A terminal job status guarantees our following read can see its last writes.
    replay = await breadth_replay.replay.status(day)
    session = await asyncio.to_thread(market_stats.read_session, day, now)
    if preview := await breadth_replay.replay.preview_for(day, replay):
        session["breadth"]["preview"] = preview
    return {**session, "backfill": {key: value for key, value in replay.items() if key != "coverage"} if replay else None}


@router.post("/market-breadth/backfill")
async def backfill_market_breadth(date: Date):
    _check_date(date)
    return {"date": date.isoformat(), "status": await breadth_replay.replay.start(date)}


@router.get("/price-catalog")
async def price_catalog(q: str = Query("", max_length=80), include_all: bool = False,
                        kind: Literal["etf", "index"] = "etf"):
    store = prices.index_store if kind == "index" else prices.store
    return await store.search(q, include_all=include_all)


@router.get("/price-line")
async def price_line(date: Date, symbol: str = Query(pattern=r"^\d{6}\.(SH|SZ)$"),
                     kind: Literal["etf", "index"] = "etf"):
    _check_date(date)
    store = prices.index_store if kind == "index" else prices.store
    return await store.load(date, symbol)
