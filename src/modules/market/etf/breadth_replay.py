"""Manual reconstruction of missing breadth slots from Tushare stock bars."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from src.modules.market.etf import intraday, market_stats
from src.modules.market.etf.models import EtfBreadthReplayResult, EtfBreadthReplayStock, EtfMarketBreadthMinute
from src.platform.marketdata import tushare_market
from src.platform.marketdata.tushare_market import TushareFailure
from src.platform.persistence.database import SessionLocal

logger = logging.getLogger(__name__)
FIRST_DATE = date(2010, 1, 1)
BEIJING_OPEN = date(2021, 11, 15)
CONCURRENCY = 4
REQUESTS_PER_SECOND = 4
MAX_CONSECUTIVE_FAILURES = 12
MAX_THROTTLE_STREAK = 5
MIN_COOLDOWN_SECONDS = 60
THROTTLED_INTERVAL_SECONDS = 1.1
HARD_FAILURES = intraday.HARD_FAILURES
MINUTE_INDEX = {minute: i for i, minute in enumerate(intraday.MINUTES)}


def _stored_result(day: date) -> dict | None:
    with SessionLocal() as db:
        row = db.get(EtfBreadthReplayResult, day.isoformat())
        return row.payload if row else None


def _targets(day: date, through: str) -> tuple[str, ...]:
    with SessionLocal() as db:
        recorded = set(db.scalars(select(EtfMarketBreadthMinute.minute)
                                  .where(EtfMarketBreadthMinute.trade_date == day.isoformat())))
    return tuple(minute for minute in intraday.MINUTES if minute <= through and minute not in recorded)


def _cached_bars(day: date, through: str | None = None) -> dict:
    with SessionLocal() as db:
        query = select(EtfBreadthReplayStock).where(EtfBreadthReplayStock.trade_date == day.isoformat())
        if through is not None:
            query = query.where(EtfBreadthReplayStock.through >= through)
        rows = db.scalars(query)
        return {row.symbol: row.bars for row in rows}


def _save_bars(day: date, batch: dict) -> None:
    with SessionLocal.begin() as db:
        for symbol, bars in batch.items():
            db.merge(EtfBreadthReplayStock(trade_date=day.isoformat(), symbol=symbol, through=max(bars), bars=bars))


def _save_outcome(day: date, result: dict, points: dict) -> None:
    with SessionLocal.begin() as db:
        if points:
            result["added"] += _insert_missing(db, day, points)
        db.merge(EtfBreadthReplayResult(trade_date=day.isoformat(), payload=result))


def _save_minutes(day: date, points: dict) -> int:
    with SessionLocal.begin() as db:
        return _insert_missing(db, day, points)


def _insert_missing(db: Session, day: date, points: dict) -> int:
    statement = insert(EtfMarketBreadthMinute.__table__).on_conflict_do_nothing(index_elements=["trade_date", "minute"])
    written = db.execute(statement, [
        {"trade_date": day.isoformat(), "minute": minute, "source": "backfill", **counts}
        for minute, counts in points.items()
    ])
    return max(0, written.rowcount)


def _live(day: date) -> bool:
    now = intraday.now_cn()
    return day == now.date() and now.time() < intraday.ARCHIVE_READY


async def _reference(day: date, fetch) -> dict[str, float]:
    live = _live(day)
    day_key = day.isoformat()
    daily_key = day.strftime("%Y%m%d")
    rows = await market_stats.market_snapshot(fetch) if live else await fetch(
        "daily", {"trade_date": daily_key}, "ts_code,trade_date,pre_close,vol",
    )
    if not live and len(rows) >= market_stats.SNAPSHOT_LIMIT:
        raise TushareFailure("unavailable")
    reference = {}
    for row in rows:
        symbol = row.get("ts_code")
        if not isinstance(symbol, str) or not market_stats.STOCK_CODE.fullmatch(symbol):
            continue
        timestamp = row.get("trade_time" if live else "trade_date")
        if not isinstance(timestamp, str) or (timestamp[:10] != day_key if live else timestamp != daily_key):
            continue
        try:
            intraday.number(row.get("vol"), positive=True)
            reference[symbol] = intraday.number(row.get("pre_close"), positive=True)
        except TushareFailure:
            continue
    expected = market_stats.VENUES if day >= BEIJING_OPEN else {"SH", "SZ"}
    if not expected.issubset({code[-2:] for code in reference}):
        raise TushareFailure("unavailable")
    return reference


async def _bars(day: date, symbol: str, through: str, fetch, *, allow_partial: bool = False) -> dict:
    # A long-running same-day task can cross the archive boundary.
    live = _live(day)
    if live:
        operation = "rt_min_daily"
        params = {"ts_code": symbol, "freq": "1MIN"}
        fields = "ts_code,time,close,vol"
    else:
        operation = "stk_mins"
        params = {"ts_code": symbol, "freq": "1min", "start_date": f"{day} 09:30:00", "end_date": f"{day} {through}:00"}
        fields = "ts_code,trade_time,close,vol"
    rows = await fetch(operation, params, fields)
    bars = {}
    for row in rows:
        stamp = row.get("time" if live else "trade_time")
        if (row.get("ts_code", row.get("code")) != symbol or not isinstance(stamp, str)
                or not intraday.TIMESTAMP.fullmatch(stamp) or stamp[:10] != day.isoformat()):
            raise TushareFailure("unavailable")
        minute = stamp[11:16]
        if minute in MINUTE_INDEX and minute <= through:
            volume = intraday.number(row.get("vol"))
            price = intraday.number(row.get("close"), positive=True) if volume else None
            if minute in bars and bars[minute] != price:
                raise TushareFailure("unavailable")
            bars[minute] = price
    if not bars or (not allow_partial and max(bars) < through):
        raise TushareFailure("unavailable")
    return bars


def _reconstruct(reference: dict, by_symbol: dict, targets: tuple[str, ...]) -> dict:
    minutes = intraday.MINUTES[:MINUTE_INDEX[targets[-1]] + 1]
    counts = [[0, 0, 0] for _ in minutes]
    observed = [set() for _ in minutes]
    venues = {symbol[-2:] for symbol in reference}
    for symbol, previous in reference.items():
        bars = by_symbol[symbol]
        venue = symbol[-2:]
        direction = None
        for i, minute in enumerate(minutes):
            if minute in bars:
                observed[i].add(venue)
                price = bars[minute]
                if price is not None:
                    direction = 0 if price > previous else 1 if price < previous else 2
            if direction is not None:
                counts[i][direction] += 1
    return {
        minute: dict(zip(("up", "down", "flat"), counts[MINUTE_INDEX[minute]], strict=True))
        for minute in targets
        if observed[MINUTE_INDEX[minute]] >= venues and sum(counts[MINUTE_INDEX[minute]]) > 0
    }


class _MinuteCoverage:
    """Track full-market coverage and counts without recomputing each batch."""

    def __init__(self, reference: dict, by_symbol: dict, targets: tuple[str, ...]):
        self.reference = reference
        self.targets = targets
        self.minutes = intraday.MINUTES[:MINUTE_INDEX[targets[-1]] + 1]
        self.indexes = tuple(MINUTE_INDEX[minute] for minute in targets)
        # 0 = unknown, 1 = confirmed no trades yet, 2..4 = up/down/flat.
        self.counts = [[0, 0, 0, 0, 0] for _ in targets]
        self.symbol_states: dict[str, bytes] = {}
        self.complete_symbols: set[str] = set()
        self.published: set[str] = set()
        for symbol in reference.keys() & by_symbol.keys():
            self.update(symbol, by_symbol[symbol])

    def update(self, symbol: str, bars: dict) -> None:
        previous = self.reference[symbol]
        direction = 1
        timeline = bytearray()
        for minute in self.minutes:
            if minute not in bars:
                # An omitted bar does not establish that no trade happened.
                direction = 0
            elif (price := bars[minute]) is not None:
                direction = 2 if price > previous else 3 if price < previous else 4
            timeline.append(direction)
        states = bytes(timeline[index] for index in self.indexes)
        old = self.symbol_states.get(symbol)
        for index, state in enumerate(states):
            counts = self.counts[index]
            if old is not None:
                counts[old[index]] -= 1
            counts[state] += 1
        self.symbol_states[symbol] = states
        if 0 not in states:
            self.complete_symbols.add(symbol)
        else:
            self.complete_symbols.discard(symbol)

    def ready(self) -> dict:
        total = len(self.reference)
        return {
            minute: {"up": up, "down": down, "flat": flat}
            for minute, (_, no_trades, up, down, flat) in zip(self.targets, self.counts, strict=True)
            if minute not in self.published and no_trades + up + down + flat == total and up + down + flat > 0
        }

    def preview(self) -> dict[str, int]:
        return {
            minute: sum(counts[1:])
            for minute, counts in zip(self.targets, self.counts, strict=True)
            if minute not in self.published and any(counts[1:])
        }


def coverage_preview(result: dict | None) -> dict | None:
    if not result or result["status"] == "complete" or not result.get("through") or not result["total"]:
        return None
    minutes = result.get("coverage")
    # Older jobs only stored how many stocks covered every target minute.
    minimum = result["processed"] if minutes is None else 0
    if not minutes and not minimum:
        return None
    return {"through": result["through"], "total": result["total"], "minimum": minimum, "minutes": minutes or {}}


class _Pacer:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.interval = 1 / REQUESTS_PER_SECOND

    async def wait(self):
        async with self.lock:
            await asyncio.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + self.interval

    def slow_down(self):
        self.interval = min(4, max(THROTTLED_INTERVAL_SECONDS, self.interval * 2))


class BreadthReplay:
    def __init__(self):
        self.task: asyncio.Task | None = None
        self.date: date | None = None
        self.progress: dict | None = None
        self.retry_after = 0.0
        # Keep spacing between requests even when adjacent jobs finish quickly.
        self.pacer = _Pacer()
        self.inflight = asyncio.Semaphore(CONCURRENCY)

    async def status(self, day: date) -> dict | None:
        if self.date == day and self.progress:
            return self.progress.copy()
        return await asyncio.to_thread(_stored_result, day)

    async def preview_for(self, day: date, result: dict | None) -> dict | None:
        if result and result["status"] == "running" and not result["total"]:
            # Keep saved coverage visible while the new task loads the stock pool.
            result = await asyncio.to_thread(_stored_result, day)
        return coverage_preview(result)

    def _rejection(self, day):
        if self.task is not None and not self.task.done():
            return "running" if self.date == day else "busy"
        if time.monotonic() < self.retry_after:
            return "cooldown"
        return None

    async def start(self, day: date) -> str:
        now = intraday.now_cn()
        through = market_stats.latest_due(day, now)
        if day < FIRST_DATE:
            return "unavailable"
        if through is None:
            return "nothing_to_fill"
        reason = self._rejection(day)
        if reason:
            return reason
        targets = await asyncio.to_thread(_targets, day, through)
        reason = self._rejection(day)
        if reason:
            return reason
        if not targets:
            return "nothing_to_fill"
        self.date = day
        self.progress = {"status": "running", "processed": 0, "total": 0, "added": 0,
                         "through": targets[-1], "reason": None}
        self.task = asyncio.create_task(self._run(day, targets, self.progress, progressive=day == now.date()),
                                        name="etf-breadth-replay")
        return "running"

    async def _request(self, operation, params, fields):
        async with self.inflight:
            await self.pacer.wait()
            remaining = self.retry_after - time.monotonic()
            if remaining > 0:
                raise TushareFailure("rate_limited", retry_after=remaining)
            try:
                return await tushare_market.rows(operation, params, fields)
            except TushareFailure as exc:
                if exc.code == "rate_limited":
                    now = time.monotonic()
                    if now >= self.retry_after:
                        self.pacer.slow_down()
                    self.retry_after = max(self.retry_after, now + max(MIN_COOLDOWN_SECONDS, exc.retry_after))
                raise

    async def _wait_for_quota(self, result: dict) -> None:
        result["reason"] = "rate_limited"
        await asyncio.sleep(max(0, self.retry_after - time.monotonic()))
        result["reason"] = None

    async def _load_reference(self, day: date, result: dict) -> dict:
        for attempt in range(MAX_THROTTLE_STREAK + 1):
            try:
                return await _reference(day, self._request)
            except TushareFailure as exc:
                if exc.code != "rate_limited" or attempt == MAX_THROTTLE_STREAK:
                    raise
                await self._wait_for_quota(result)

    async def _publish_ready(self, day: date, coverage: _MinuteCoverage, result: dict) -> None:
        if points := coverage.ready():
            result["added"] += await asyncio.to_thread(_save_minutes, day, points)
            coverage.published.update(points)
        result["coverage"] = coverage.preview()

    async def _run(self, day: date, targets: tuple[str, ...], result: dict, *, progressive: bool):
        points = {}
        status = "failed"
        reason = "unavailable"
        try:
            through = targets[-1]
            reference = await self._load_reference(day, result)
            by_symbol = await asyncio.to_thread(_cached_bars, day, None if progressive else through)
            coverage = await asyncio.to_thread(_MinuteCoverage, reference, by_symbol, targets) if progressive else None
            pending = deque(sorted(reference.keys() - (coverage.complete_symbols if coverage else by_symbol.keys())))
            result.update(processed=len(reference) - len(pending), total=len(reference))
            if coverage is not None:
                await self._publish_ready(day, coverage, result)
            failed_without_progress = 0
            throttle_streak = 0
            while pending:
                symbols = [pending.popleft() for _ in range(min(len(pending), CONCURRENCY))]
                rows = await asyncio.gather(
                    *(_bars(day, symbol, through, self._request, allow_partial=progressive) for symbol in symbols),
                    return_exceptions=True,
                )
                successes = {symbol: row for symbol, row in zip(symbols, rows, strict=True) if isinstance(row, dict)}
                if successes:
                    if coverage is not None:
                        # A lagging response may be shorter than the saved series.
                        successes = {symbol: {**by_symbol.get(symbol, {}), **bars} for symbol, bars in successes.items()}
                    await asyncio.to_thread(_save_bars, day, successes)
                    by_symbol.update(successes)
                    if coverage is not None:
                        for symbol, bars in successes.items():
                            coverage.update(symbol, bars)
                        result["processed"] = len(coverage.complete_symbols)
                        await self._publish_ready(day, coverage, result)
                    else:
                        result["processed"] += len(successes)
                    failed_without_progress = 0
                    throttle_streak = 0
                limited = []
                for symbol, row in zip(symbols, rows, strict=True):
                    if isinstance(row, TushareFailure) and row.code == "rate_limited":
                        limited.append(symbol)
                        continue
                    if isinstance(row, TushareFailure) and row.code in HARD_FAILURES:
                        raise row
                    if isinstance(row, BaseException) and not isinstance(row, TushareFailure):
                        raise row
                if limited:
                    throttle_streak += 1
                    if throttle_streak > MAX_THROTTLE_STREAK:
                        raise TushareFailure("rate_limited")
                    pending.extendleft(reversed(limited))
                    await self._wait_for_quota(result)
                    continue
                if not successes:
                    failed_without_progress += len(symbols)
                if failed_without_progress >= MAX_CONSECUTIVE_FAILURES:
                    raise TushareFailure("unavailable")
            if coverage is not None:
                remaining = await asyncio.to_thread(_targets, day, through)
                missing = set(targets).intersection(remaining)
                status, reason = ("partial", "missing_minutes") if missing else ("complete", None)
            elif result["processed"] == result["total"]:
                points = await asyncio.to_thread(_reconstruct, reference, by_symbol, targets)
                status, reason = ("complete", None) if len(points) == len(targets) else ("partial", "missing_minutes")
            else:
                status, reason = "partial", "missing_stocks"
            if status == "complete":
                from src.modules.market.etf import linked
                await asyncio.to_thread(linked.save_reconstructed, day, reference, by_symbol, targets, sessions=SessionLocal)
        except TushareFailure as exc:
            reason = exc.code
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            logger.exception("ETF market breadth backfill failed (%s)", day)
        finally:
            try:
                if status != "cancelled":
                    # Report a terminal state only after its minutes are visible to readers.
                    await asyncio.to_thread(_save_outcome, day, {**result, "status": status, "reason": reason}, points)
            except Exception:
                logger.exception("ETF market breadth backfill result could not be saved (%s)", day)
            finally:
                self.progress = None

    async def shutdown(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


replay = BreadthReplay()
