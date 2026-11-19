"""Scheduled Tushare snapshots and read-only statistics for the ETF page."""
from __future__ import annotations

import asyncio
import logging
import re
from bisect import bisect_right
from datetime import date, datetime, time, timedelta
from math import fsum

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.modules.market.etf import intraday
from src.modules.market.etf.models import EtfDailyShares, EtfIntradayDay, EtfMarketBreadthMinute, EtfTushareUniverse
from src.modules.market.etf.universe import SAMPLE, UNIVERSE_KEY
from src.platform.marketdata import tushare_market
from src.platform.marketdata.tushare_market import TushareFailure
from src.platform.persistence.database import SessionLocal
from src.platform.scheduling import scheduler_registry, trading_calendar

logger = logging.getLogger(__name__)
SAMPLE_SECOND = 4
SAMPLE_GRACE = 5
SHARES_READY = time(8, 35)
A_SHARE_GROUPS = ("6*.SH", "0*.SZ", "3*.SZ", "9*.BJ")
STOCK_CODE = re.compile(r"(?:6\d{5}\.SH|[03]\d{5}\.SZ|9\d{5}\.BJ)")
VENUES = {"SH", "SZ", "BJ"}
SNAPSHOT_LIMIT = 6000


def minute_slot(moment: datetime) -> str | None:
    minute = moment.strftime("%H:%M")
    return minute if (
        SAMPLE_SECOND <= moment.second <= SAMPLE_SECOND + SAMPLE_GRACE
        and minute in intraday.MINUTE_SET
        and trading_calendar.is_trading_day("CN", moment.date())
    ) else None


def previous_trading_day(day: date) -> date | None:
    for offset in range(1, 32):
        candidate = day - timedelta(days=offset)
        if not trading_calendar.calendar_known("CN", candidate):
            return None
        if trading_calendar.is_trading_day("CN", candidate):
            return candidate
    return None


def breadth_counts(rows, day: date, minute: str) -> dict | None:
    date_prefix = day.isoformat()
    by_symbol = {}
    fresh_venues = set()
    for row in rows:
        symbol, stamp = row.get("ts_code"), row.get("trade_time")
        if not isinstance(symbol, str) or not STOCK_CODE.fullmatch(symbol):
            continue
        if not isinstance(stamp, str) or len(stamp) < 19 or stamp[:10] != date_prefix:
            continue
        snapshot_minute = stamp[11:16]
        if snapshot_minute > minute:
            continue
        try:
            close = intraday.number(row.get("close"), positive=True)
            previous = intraday.number(row.get("pre_close"), positive=True)
            intraday.number(row.get("vol"), positive=True)
        except TushareFailure:
            continue
        if snapshot_minute == minute:
            fresh_venues.add(symbol[-2:])
        if symbol not in by_symbol or stamp > by_symbol[symbol][0]:
            by_symbol[symbol] = (stamp, close, previous)
    # A stale feed or a missing exchange must not appear as a change in breadth.
    if fresh_venues != VENUES:
        return None
    counts = dict.fromkeys(("up", "down", "flat"), 0)
    for _, close, previous in by_symbol.values():
        counts["up" if close > previous else "down" if close < previous else "flat"] += 1
    return counts


def _has_breadth(day: date, minute: str) -> bool:
    with SessionLocal() as db:
        return db.get(EtfMarketBreadthMinute, (day.isoformat(), minute)) is not None


def _save_breadth(day: date, minute: str, counts: dict) -> None:
    with SessionLocal() as db:
        db.add(EtfMarketBreadthMinute(trade_date=day.isoformat(), minute=minute, **counts))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.get(EtfMarketBreadthMinute, (day.isoformat(), minute)) is None:
                raise


async def market_snapshot(fetch=None):
    fetch = fetch or tushare_market.rows
    fields = "ts_code,trade_time,close,pre_close,vol"
    rows = await fetch("rt_k", {"ts_code": ",".join(A_SHARE_GROUPS)}, fields)
    if len(rows) >= SNAPSHOT_LIMIT:
        groups = await asyncio.gather(*(fetch("rt_k", {"ts_code": group}, fields) for group in A_SHARE_GROUPS))
        if any(len(group) >= SNAPSHOT_LIMIT for group in groups):
            raise TushareFailure("unavailable")
        rows = [row for group in groups for row in group]
    return rows


async def capture_breadth() -> None:
    now = intraday.now_cn()
    minute = minute_slot(now)
    if minute is None or await asyncio.to_thread(_has_breadth, now.date(), minute):
        return
    try:
        rows = await market_snapshot()
    except TushareFailure as exc:
        logger.debug("ETF breadth snapshot unavailable (%s): %s", minute, exc.code)
        return
    # Slow responses can cross into the next minute. Filter provider timestamps
    # to the scheduled slot rather than assigning later data to a missed minute.
    counts = breadth_counts(rows, now.date(), minute)
    if counts is not None:
        await asyncio.to_thread(_save_breadth, now.date(), minute, counts)
        from src.modules.market.etf import linked
        await asyncio.to_thread(linked.capture_observation, now.date(), minute, rows, sessions=SessionLocal)


def _shares(day: date) -> dict:
    with SessionLocal() as db:
        row = db.get(EtfDailyShares, day.isoformat())
        return row.payload if row else {}


def _members(day: date) -> tuple[str, ...]:
    key = day.isoformat()
    with SessionLocal() as db:
        session = db.get(EtfIntradayDay, key)
        if session is not None and session.parts.get("universe_key") == UNIVERSE_KEY:
            return tuple(session.parts["members"])
        universe = db.get(EtfTushareUniverse, UNIVERSE_KEY)
        if universe is not None:
            return tuple(symbol for symbol, listed in universe.payload["listed"].items() if listed <= key)
    return SAMPLE


def _save_shares(day: date, payload: dict) -> None:
    if not payload:
        return
    with SessionLocal.begin() as db:
        key = day.isoformat()
        row = db.get(EtfDailyShares, key)
        if row is None:
            db.add(EtfDailyShares(trade_date=key, payload=payload))
        else:
            combined = dict(row.payload)
            for symbol, current in payload.items():
                combined[symbol] = {**combined.get(symbol, {}), **current}
            row.payload = combined


async def _capture_shares(day: date, members: tuple[str, ...], *, needs_nav: bool) -> None:
    saved = await asyncio.to_thread(_shares, day)
    if all(symbol in saved and (not needs_nav or "nav" in saved[symbol]) for symbol in members):
        return
    data_date = day.strftime("%Y%m%d")
    rows = await tushare_market.rows("etf_share_size", {"trade_date": data_date},
                                    "ts_code,trade_date,total_share,nav")
    snapshot = {}
    for row in rows:
        symbol = row.get("ts_code")
        if symbol not in SAMPLE or row.get("trade_date") != data_date:
            continue
        try:
            shares = intraday.number(row.get("total_share"), positive=True)
        except TushareFailure:
            continue
        values = {"shares": shares}
        try:
            values["nav"] = intraday.number(row.get("nav"), positive=True)
        except TushareFailure:
            pass
        snapshot[symbol] = values
    await asyncio.to_thread(_save_shares, day, snapshot)


async def capture_daily_flows() -> None:
    now = intraday.now_cn()
    if now.time() < SHARES_READY:
        return
    day = previous_trading_day(now.date())
    reference = previous_trading_day(day) if day else None
    if day is None or reference is None:
        return
    try:
        members = await asyncio.to_thread(_members, day)
        await _capture_shares(day, members, needs_nav=True)
        if await asyncio.to_thread(_shares, day):
            await _capture_shares(reference, members, needs_nav=False)
    except TushareFailure as exc:
        logger.debug("ETF daily shares unavailable (%s): %s", day, exc.code)


def latest_closed_minute(day: date, now: datetime) -> str | None:
    if not trading_calendar.is_trading_day("CN", day):
        return None
    if day < now.date():
        return intraday.MINUTES[-1]
    if day > now.date():
        return None
    end = bisect_right(intraday.MINUTES, now.strftime("%H:%M"))
    return intraday.MINUTES[end - 1] if end else None


def latest_due(day: date, now: datetime) -> str | None:
    # Allow the scheduled fetch to finish before reporting a minute as missing.
    grace = timedelta(seconds=SAMPLE_SECOND + SAMPLE_GRACE + 8)
    return latest_closed_minute(day, now - grace)


def read_session(day: date, now: datetime) -> dict:
    day_key = day.isoformat()
    closed = latest_closed_minute(day, now)
    points = {}
    if closed is not None:
        with SessionLocal() as db:
            minutes = db.scalars(select(EtfMarketBreadthMinute)
                                 .where(EtfMarketBreadthMinute.trade_date == day_key, EtfMarketBreadthMinute.minute <= closed)
                                 .order_by(EtfMarketBreadthMinute.minute))
            points = {row.minute: {"up": row.up, "down": row.down, "flat": row.flat,
                                   **({"source": "backfill"} if row.source == "backfill" else {})}
                      for row in minutes if row.minute in intraday.MINUTE_SET}
    through = max(points.keys() | {latest_due(day, now) or ""}) or None

    reference = previous_trading_day(day)
    current = _shares(day)
    before = _shares(reference) if reference and current else {}
    members = _members(day)
    values = [
        (current[symbol]["shares"] - before[symbol]["shares"]) * 10_000 * current[symbol]["nav"]
        for symbol in members if symbol in current and symbol in before and "nav" in current[symbol]
    ]
    total, covered = len(members), len(values)
    pending = trading_calendar.is_trading_day("CN", day) and now < datetime.combine(
        day + timedelta(days=1), SHARES_READY, intraday.CN,
    )
    status = "ready" if total and covered == total else "partial" if covered else "pending" if pending else "unavailable"
    return {
        "date": day_key,
        "breadth": {"through": through, "points": points},
        "daily_flow": {"status": status, "total": total, "covered": covered,
                       "net_cny": round(fsum(values), 2) if status == "ready" else None},
    }


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=intraday.CN)
    scheduler.add_job(capture_breadth, "cron", day_of_week="mon-fri", hour="9-11,13-15",
                      second=SAMPLE_SECOND, misfire_grace_time=SAMPLE_GRACE, coalesce=True, max_instances=1,
                      id="etf_market_breadth")
    # The latest completed trading day is the only target. Recheck while the
    # provider is publishing it in batches; complete snapshots skip the API.
    scheduler.add_job(capture_daily_flows, "cron", hour="8-23", minute="5,35",
                      next_run_time=intraday.now_cn(), coalesce=True, max_instances=1,
                      id="etf_daily_flows")
    scheduler.start()
    scheduler_registry.register("etf_market_stats", scheduler)
    return scheduler
