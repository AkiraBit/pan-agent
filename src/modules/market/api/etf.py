"""Authenticated Tushare intraday read, backed by the per-session database."""
from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, Query

from src.modules.market.etf import intraday, market_stats, prices
from src.web.errors import api_error

router = APIRouter()


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
def session_market_stats(date: Date | None = None):
    if date:
        _check_date(date)
    now = intraday.now_cn()
    return market_stats.read_session(date or intraday.latest_session(now), now)


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
