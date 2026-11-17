"""Tushare minute observations for a domestic ETF watchlist."""
from __future__ import annotations

import asyncio
import re
from bisect import bisect_right
from datetime import date, datetime, time, timedelta
from math import fsum, isfinite
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.modules.market.etf.models import EtfIntradayDay, EtfTurnoverBaseline, EtfTushareUniverse
from src.modules.market.etf.universe import DISCLOSURES, SAMPLE, SAMPLE_BENCHMARKS, UNIVERSE_KEY
from src.platform.marketdata import tushare_market
from src.platform.marketdata.tushare_market import TushareFailure
from src.platform.persistence.database import SessionLocal
from src.platform.scheduling import trading_calendar

CN = ZoneInfo("Asia/Shanghai")
INDEX = "000001.SH"
FIRST_DATE = date(2009, 1, 1)
OPEN = time(9, 30)
ARCHIVE_READY = time(21)
LIVE_COOLDOWN = 60
LIVE_SLOT_RETRY = 15
HISTORY_RETRY = 180
BASELINE_SESSIONS = 5
BASELINE_VERSION = 1
# Tushare publishes the opening auction plus bars labelled by the end of each minute.
MINUTES = tuple(f"{minute // 60:02}:{minute % 60:02}"
                for start, end in ((570, 691), (781, 901)) for minute in range(start, end))
MINUTE_SET = frozenset(MINUTES)
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:00")
HARD_FAILURES = {"source_disabled", "key_required", "permission_required", "rate_limited"}


def now_cn() -> datetime:
    return datetime.now(CN)


def is_closed(day: date) -> bool:
    return trading_calendar.calendar_known("CN", day) and not trading_calendar.is_trading_day("CN", day)


def adjacent(day: date, direction: int, today: date) -> str | None:
    for offset in range(1, 32):
        candidate = day + timedelta(days=direction * offset)
        if not FIRST_DATE <= candidate <= today:
            break
        if not is_closed(candidate):
            return candidate.isoformat()
    return None


def market_clock():
    moment = now_cn()
    today = moment.date()
    return {
        "at": moment.isoformat(timespec="milliseconds"),
        "date": today.isoformat(),
        "timezone": CN.key,
        "trading_day": not is_closed(today),
        "next_trading_day": adjacent(today, 1, today + timedelta(days=31)),
    }


def latest_session(moment: datetime) -> date:
    today = moment.date()
    if not is_closed(today) and moment.time() >= OPEN:
        return today
    previous = adjacent(today, -1, today)
    return date.fromisoformat(previous) if previous else today


def number(raw, *, positive=False):
    if type(raw) not in {str, float, int}:
        raise TushareFailure("unavailable")
    try:
        value = float(raw)
    except (ValueError, OverflowError):
        raise TushareFailure("unavailable") from None
    if not isfinite(value) or value < 0 or (positive and value == 0):
        raise TushareFailure("unavailable")
    return value


def minute_series(rows, day, symbol, value_key, *, live=False, keep_first=False):
    result = {}
    for row in rows:
        stamp = row.get("time" if live else "trade_time")
        # The official intraday docs and some relays use `code` rather than `ts_code`.
        if row.get("ts_code", row.get("code")) != symbol or not isinstance(stamp, str) or not TIMESTAMP.fullmatch(stamp):
            raise TushareFailure("unavailable")
        if stamp[:10] != day.isoformat():
            raise TushareFailure("unavailable")
        minute = stamp[11:16]
        if minute not in MINUTE_SET:
            continue
        if minute in result:
            if keep_first:
                continue
            raise TushareFailure("unavailable")
        result[minute] = number(row.get(value_key), positive=value_key == "close")
    return result


def full_session(part):
    return (part.get("data") or {}).keys() >= MINUTE_SET


def baseline_basis(day, selected):
    symbols = selected.get("members", [])
    if selected.get("universe_key") != UNIVERSE_KEY or not symbols:
        return None
    days = []
    cursor = day
    for _ in range(BASELINE_SESSIONS):
        previous = adjacent(cursor, -1, day)
        if not previous:
            return None
        days.insert(0, previous)
        cursor = date.fromisoformat(previous)
    return {"version": BASELINE_VERSION, "universe": UNIVERSE_KEY, "symbols": sorted(symbols), "days": days}


def market_universe(etfs, benchmarks):
    broad_indexes = {row.get("ts_code") for row in benchmarks if row.get("bmk_type") in {"宽基", "宽基指数"}}
    if not broad_indexes:
        raise TushareFailure("unavailable")
    broad_funds = set()
    listed_funds = {}
    names = {}
    for row in etfs:
        symbol = row.get("ts_code")
        if (not isinstance(symbol, str) or not re.fullmatch(r"\d{6}\.(SH|SZ)", symbol)
                or row.get("list_status") != "L" or row.get("etf_type") not in {"境内", "纯境内"}):
            continue
        try:
            listed = datetime.strptime(row["list_date"], "%Y%m%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        index_code = row.get("index_code")
        is_broad = index_code in broad_indexes
        if is_broad:
            broad_funds.add(symbol)
        if symbol in SAMPLE and (is_broad or (index_code and index_code == SAMPLE_BENCHMARKS.get(symbol))):
            listed_funds[symbol] = listed.isoformat()
            name = row.get("csname")
            if isinstance(name, str) and name.strip():
                names[symbol] = name.strip()
    if not broad_funds:
        raise TushareFailure("unavailable")
    return {"broad_count": len(broad_funds),
            "listed": {symbol: listed_funds[symbol] for symbol in SAMPLE if symbol in listed_funds},
            "names": names}


class IntradayStore:
    def __init__(self):
        self._locks = tuple(asyncio.Lock() for _ in range(32))
        self._universe_lock = asyncio.Lock()
        self._baseline_lock = asyncio.Lock()
        self._baseline_retry = {}
        self._slots = asyncio.Semaphore(4)
        self._rate_until = 0.0
        self._universe_failure = None

    def _day_lock(self, day):
        return self._locks[day.toordinal() % len(self._locks)]

    def _read(self, day):
        with SessionLocal() as db:
            row = db.get(EtfIntradayDay, day.isoformat())
            return row.parts if row else {}

    def _save(self, day, parts):
        with SessionLocal() as db:
            row = db.get(EtfIntradayDay, day.isoformat())
            if row is None:
                db.add(EtfIntradayDay(trade_date=day.isoformat(), parts=parts))
            else:
                before = row.parts.get("parts", {})
                after = parts.get("parts", {})
                if any(before.get(code, {}).get("data") != after.get(code, {}).get("data")
                       for code in before.keys() | after.keys() if code not in (INDEX, "reference")):
                    row.turnover_revision += 1
                row.parts = parts
            db.commit()

    def _read_baseline(self, day, basis):
        with SessionLocal() as db:
            row = db.get(EtfTurnoverBaseline, day.isoformat())
            if not row or row.payload.get("basis") != basis:
                return None
            revisions = dict(db.execute(select(EtfIntradayDay.trade_date, EtfIntradayDay.turnover_revision)
                                        .where(EtfIntradayDay.trade_date.in_(basis["days"]))).all())
            return row.payload["result"] if revisions == row.payload.get("revisions") else None

    def _read_baseline_inputs(self, days):
        by_key = {day.isoformat(): day for day in days}
        with SessionLocal() as db:
            rows = db.scalars(select(EtfIntradayDay).where(EtfIntradayDay.trade_date.in_(by_key))).all()
            parts = {day: {} for day in days}
            revisions = {}
            for row in rows:
                parts[by_key[row.trade_date]] = row.parts.get("parts", {})
                revisions[row.trade_date] = row.turnover_revision
            return parts, revisions

    def _save_baseline(self, day, basis, revisions, result):
        with SessionLocal() as db:
            db.merge(EtfTurnoverBaseline(trade_date=day.isoformat(),
                                        payload={"basis": basis, "revisions": revisions, "result": result}))
            db.commit()

    async def _baseline_status(self, day, saved, session):
        turnover = [point for point in session["points"] if point["turnover_cny"] is not None]
        if not turnover:
            return {"status": "unavailable"}
        basis = baseline_basis(day, saved)
        if basis is None:
            return {"status": "unavailable"}
        cached = await asyncio.to_thread(self._read_baseline, day, basis)
        if cached is not None:
            return {"status": "ready", "value": cached}
        if not any(point["etf_count"] == len(session["symbols"]) for point in turnover):
            return {"status": "unavailable"}
        if self._baseline_retry.get(day, 0) > now_cn().timestamp() or not await self._baseline_listed(basis):
            return {"status": "unavailable"}
        return {"status": "needs_calculation"}

    async def _baseline_listed(self, basis):
        _, universe = await asyncio.to_thread(self._read_universe)
        return not universe or all(universe["listed"].get(symbol, "9999") <= basis["days"][0] for symbol in basis["symbols"])

    async def _session(self, day, base, saved, mode, cached, *, issues=()):
        session = summary(base, saved, mode, cached, issues=issues)
        session["turnover_baseline"] = await self._baseline_status(day, saved, session)
        return session

    def _read_universe(self):
        with SessionLocal() as db:
            rec = db.get(EtfTushareUniverse, UNIVERSE_KEY)
            return (rec.updated_on, rec.payload) if rec else (None, None)

    def _save_universe(self, today, payload):
        with SessionLocal() as db:
            db.merge(EtfTushareUniverse(key=UNIVERSE_KEY, updated_on=today.isoformat(), payload=payload))
            db.commit()

    async def _query(self, operation, params, fields=""):
        async with self._slots:
            epoch = now_cn().timestamp()
            if epoch < self._rate_until:
                raise TushareFailure("rate_limited", retry_after=self._rate_until - epoch)
            try:
                return await tushare_market.rows(operation, params, fields)
            except TushareFailure as err:
                if err.code == "rate_limited":
                    self._rate_until = now_cn().timestamp() + err.retry_after
                raise

    async def _universe(self, today):
        async with self._universe_lock:
            updated_on, cached = await asyncio.to_thread(self._read_universe)
            if cached is not None and updated_on >= (today - timedelta(days=6)).isoformat():
                return cached
            if self._universe_failure and now_cn().timestamp() < self._universe_failure[0]:
                if cached is not None:
                    return cached
                raise TushareFailure(self._universe_failure[1])
            try:
                etfs = await self._query("etf_basic", {"list_status": "L"},
                                         "ts_code,csname,index_code,list_date,list_status,etf_type")
                benchmarks = await self._query("mkt_idx_bmk", {"bmk_type": "宽基"}, "ts_code,bmk_type")
                payload = market_universe(etfs, benchmarks)
            except TushareFailure as err:
                self._universe_failure = (now_cn().timestamp() + max(30, err.retry_after), err.code)
                if cached is not None:
                    return cached
                raise
            self._universe_failure = None
            await asyncio.to_thread(self._save_universe, today, payload)
            return payload

    async def _reference(self, day):
        first, last = day - timedelta(days=31), day - timedelta(days=1)
        rows = await self._query("index_daily", {"ts_code": INDEX, "start_date": first.strftime("%Y%m%d"),
                               "end_date": last.strftime("%Y%m%d")}, "ts_code,trade_date,close")
        found = {}
        for row in rows:
            try:
                key = datetime.strptime(row["trade_date"], "%Y%m%d").date()
            except (KeyError, TypeError, ValueError):
                raise TushareFailure("unavailable") from None
            if row.get("ts_code") != INDEX or not first <= key <= last or key in found:
                raise TushareFailure("unavailable")
            found[key] = number(row.get("close"), positive=True)
        if not found:
            raise TushareFailure("unavailable")
        latest = max(found)
        return {"date": latest.isoformat(), "close": found[latest]}

    async def _series(self, symbol, day, mode):
        index = symbol == INDEX
        value = "close" if index else "amount"
        if mode == "live":
            rows = await self._query("rt_idx_min_daily" if index else "rt_etf_min_daily",
                                     {"ts_code": symbol, "freq": "1MIN"})
        else:
            rows = await self._query("idx_mins" if index else "etf_mins", {
                "ts_code": symbol, "freq": "1min", "start_date": f"{day} 09:30:00", "end_date": f"{day} 15:00:00",
            }, f"ts_code,trade_time,{value}")
        return minute_series(rows, day, symbol, value, live=mode == "live")

    async def _latest(self, symbols, day):
        index = symbols == (INDEX,)
        rows = await self._query("rt_idx_min" if index else "rt_etf_min",
                                 {"ts_code": ",".join(symbols), "freq": "1MIN"})
        grouped = {symbol: [] for symbol in symbols}
        for row in rows:
            symbol = row.get("ts_code", row.get("code"))
            if symbol not in grouped:
                raise TushareFailure("unavailable")
            grouped[symbol].append(row)
        return {symbol: minute_series(group, day, symbol, "close" if index else "amount", live=True)
                for symbol, group in grouped.items()}

    async def _backfill_turnover(self, symbol, days):
        rows = await self._query("etf_mins", {
            "ts_code": symbol, "freq": "1min",
            "start_date": f"{days[0]} 09:30:00", "end_date": f"{days[-1]} 15:00:00",
        }, "ts_code,trade_time,amount")
        grouped = {day.isoformat(): [] for day in days}
        for row in rows:
            stamp = row.get("trade_time")
            if (not isinstance(stamp, str) or not TIMESTAMP.fullmatch(stamp)
                    or stamp[:10] not in grouped or row.get("ts_code") != symbol):
                raise TushareFailure("unavailable")
            grouped[stamp[:10]].append(row)
        result = {}
        for day in days:
            try:
                result[day] = minute_series(grouped[day.isoformat()], day, symbol, "amount")
            except TushareFailure:
                # A bad session should not discard the other dates in this batch.
                continue
        return result

    async def turnover_baseline(self, day):
        """Average cumulative turnover at each minute, using the same basket."""
        async with self._baseline_lock:
            selected = await asyncio.to_thread(self._read, day)
            basis = baseline_basis(day, selected)
            if basis is None:
                return None
            symbols = selected["members"]
            days = [date.fromisoformat(key) for key in basis["days"]]
            cached = await asyncio.to_thread(self._read_baseline, day, basis)
            if cached is not None:
                return cached
            parts, revisions = await asyncio.to_thread(self._read_baseline_inputs, days)
            ranges = []
            for symbol in symbols:
                missing = []
                for key in days:
                    if not full_session(parts[key].get(symbol, {})):
                        missing.append(key)
                    elif missing:
                        ranges.append((symbol, missing))
                        missing = []
                if missing:
                    ranges.append((symbol, missing))

            if ranges:
                now = now_cn().timestamp()
                self._baseline_retry = {key: until for key, until in self._baseline_retry.items() if until > now}
                if day in self._baseline_retry:
                    return None
                # Do not keep asking for minutes before a fund was listed.
                if not await self._baseline_listed(basis):
                    return None
                updates = {key: {} for key in days}

                async def fetch(symbol, keys):
                    try:
                        series = await self._backfill_turnover(symbol, keys)
                    except TushareFailure as err:
                        return err.code
                    for key, values in series.items():
                        if values:
                            updates[key][symbol] = values
                    return None

                error = await fetch(*ranges[0])
                if error not in HARD_FAILURES:
                    await asyncio.gather(*(fetch(symbol, keys) for symbol, keys in ranges[1:]))
                for key, changes in updates.items():
                    if changes:
                        async with self._day_lock(key):
                            await asyncio.to_thread(self._save_turnover_parts, key, changes)
                parts, revisions = await asyncio.to_thread(self._read_baseline_inputs, days)
                if any(not full_session(parts[key].get(symbol, {})) for key in days for symbol in symbols):
                    self._baseline_retry[day] = now_cn().timestamp() + HISTORY_RETRY
                    return None

            cumulative = 0.0
            averages = {}
            for minute in MINUTES:
                cumulative += fsum(parts[key][symbol]["data"][minute] for key in days for symbol in symbols) / len(days)
                averages[minute] = cumulative
            result = {"sessions": len(days), "cumulative_cny": averages}
            await asyncio.to_thread(self._save_baseline, day, basis, revisions, result)
            return result

    def _save_turnover_parts(self, day, changes):
        saved = self._read(day)
        parts = saved.setdefault("parts", {})
        touched = False
        for symbol, values in changes.items():
            existing = parts.get(symbol, {})
            if full_session(existing):
                continue
            merged = {**(existing.get("data") or {}), **values}
            if MINUTE_SET <= merged.keys():
                parts[symbol] = {"data": merged, "mode": "archive"}
            else:
                parts[symbol] = {**existing, "data": merged}
            touched = True
        if touched:
            self._save(day, saved)

    async def load(self, day: date | None, *, refresh=False):
        moment = now_cn()
        today = moment.date()
        latest = latest_session(moment)
        day = day or latest
        mode = "live" if day == today and moment.time() < ARCHIVE_READY else "archive"
        base = {"date": day.isoformat(), "today": today.isoformat(), "latest": latest.isoformat(),
                "previous": adjacent(day, -1, today), "next": adjacent(day, 1, today),
                "source": "tushare"}
        if is_closed(day) or (day == today and moment.time() < OPEN):
            return await self._session(day, base, {}, "closed" if is_closed(day) else "waiting", True)

        async with self._day_lock(day):
            saved = await asyncio.to_thread(self._read, day)
            parts = saved.get("parts", {})
            members = saved.get("members")
            if members is None or saved.get("universe_key") != UNIVERSE_KEY:
                try:
                    universe = await self._universe(today)
                except TushareFailure as err:
                    return await self._session(day, base, saved, mode, bool(saved), issues=[err.code])
                members = [symbol for symbol, listed in universe["listed"].items() if listed <= day.isoformat()]
                # Keep existing minute series, including archived ones, when the
                # watchlist changes. Only missing members need new requests.
                saved = {"universe_key": UNIVERSE_KEY, "members": members,
                         "broad_count": universe["broad_count"], "names": universe["names"], "parts": parts}
                touched = True
            else:
                touched = False
            requests = {}
            clock = moment.strftime("%H:%M")
            latest_slot = max(0, bisect_right(MINUTES, clock) - 1)
            slot = MINUTES[latest_slot]
            predecessor = MINUTES[max(0, latest_slot - 1)]

            def due(symbol, target):
                part = parts.get(symbol, {})
                if part.get("mode") == "archive":
                    return False
                if part.get("attempt_mode") != target:
                    return True
                if target == "live" and not part.get("issue"):
                    values = part.get("data", {})
                    if slot in values:
                        return False
                    if part.get("attempt_slot") != slot:
                        return refresh or not values
                if now_cn().timestamp() < part["retry_at"]:
                    return False
                return target != "live" or refresh or not part.get("data")

            def success(symbol, target, values):
                previous = parts.get(symbol, {}).get("data", {})
                if symbol != "reference":
                    if target == "archive" and previous and (not values or max(values) < max(previous)):
                        raise TushareFailure("unavailable")
                    if target == "live" or (symbol != INDEX and values):
                        values = {**previous, **values}
                    elif day == today and not values:
                        raise TushareFailure("unavailable")
                parts[symbol] = {"data": values, "mode": target, "attempt_mode": target,
                                 "retry_at": now_cn().timestamp() + LIVE_SLOT_RETRY}
                if target == "live":
                    parts[symbol]["attempt_slot"] = slot

            def failure(symbol, target, err):
                base_delay = LIVE_COOLDOWN if target == "live" else HISTORY_RETRY
                if err.code in {"key_required", "source_disabled"}:
                    base_delay = 15
                parts[symbol] = {**parts.get(symbol, {}), "issue": err.code, "attempt_mode": target,
                                 "retry_at": now_cn().timestamp() + max(base_delay, err.retry_after)}

            async def fetch(symbol, target, loader):
                try:
                    success(symbol, target, await loader())
                except TushareFailure as err:
                    failure(symbol, target, err)
                    return err.code
                return None

            pending = [symbol for symbol in members if due(symbol, mode)]
            # If the last seen bar is only one exchange minute behind, a single
            # batch request adds the next bars without downloading the full session again.
            def last_seen(symbol):
                return max(parts.get(symbol, {}).get("data", {}), default="")

            def continuous(symbol, values):
                # An unchanged/empty latest response means this bar has not arrived.
                # Only download the full session when the new bar skips a minute.
                return not values or MINUTES.index(max(values)) <= MINUTES.index(last_seen(symbol)) + 1

            if mode == "live" and refresh:
                near = tuple(symbol for symbol in pending if last_seen(symbol) >= predecessor)
                if near:
                    try:
                        for symbol, values in (await self._latest(near, day)).items():
                            if continuous(symbol, values):
                                success(symbol, mode, values)
                                pending.remove(symbol)
                                touched = True
                    except TushareFailure as err:
                        # Optional latest endpoint can be disabled while the all-day endpoint works.
                        if err.code == "rate_limited":
                            for symbol in near:
                                failure(symbol, mode, err)
                                pending.remove(symbol)
                            touched = True
            if due(INDEX, mode):
                async def index_update():
                    if mode == "live" and refresh and last_seen(INDEX) >= predecessor:
                        try:
                            values = (await self._latest((INDEX,), day))[INDEX]
                            if continuous(INDEX, values):
                                return values
                        except TushareFailure as err:
                            if err.code == "rate_limited":
                                raise
                    return await self._series(INDEX, day, mode)
                requests[INDEX] = (mode, index_update)
            if due("reference", "archive"):
                requests["reference"] = ("archive", lambda: self._reference(day))
            if requests:
                await asyncio.gather(*(fetch(symbol, target, loader) for symbol, (target, loader) in requests.items()))
                touched = True

            # One probe avoids submitting the entire basket if its endpoint is not entitled.
            if pending:
                first, *rest = pending
                error = await fetch(first, mode, lambda: self._series(first, day, mode))
                if error in HARD_FAILURES:
                    for symbol in rest:
                        failure(symbol, mode, TushareFailure(error))
                else:
                    await asyncio.gather(*(fetch(symbol, mode, lambda symbol=symbol: self._series(symbol, day, mode))
                                           for symbol in rest))
                touched = True
            if touched:
                await asyncio.to_thread(self._save, day, saved)
            return await self._session(day, base, saved, mode, not touched)


def summary(base, saved, mode, cached, *, issues=()):
    parts = saved.get("parts", {})
    symbols = saved.get("members", [])
    names = saved.get("names", {})
    index = parts.get(INDEX, {}).get("data") or {}
    funds = [parts.get(symbol, {}).get("data") or {} for symbol in symbols]
    reference = parts.get("reference", {}).get("data") or {}
    points = []
    for minute in MINUTES:
        amounts = [fund[minute] for fund in funds if minute in fund]
        close = index.get(minute)
        if amounts or close is not None:
            points.append({"minute": minute, "turnover_cny": fsum(amounts) if amounts else None,
                           "etf_count": len(amounts), "index_close": close})
    archived = all(parts.get(component, {}).get("mode") == "archive" for component in (INDEX, "reference", *symbols))
    return {
        **base, "status": mode, "cached": cached, "archived": archived, "symbols": symbols,
        "issues": sorted(set(issues) | {parts[key]["issue"] for key in (INDEX, "reference", *symbols)
                                        if parts.get(key, {}).get("issue")}),
        "previous_close": reference.get("close"), "previous_close_date": reference.get("date"),
        "etf_count": sum(bool(fund) for fund in funds), "points": points, "broad_count": saved.get("broad_count"),
        "names": {symbol: names[symbol] for symbol in symbols if symbol in names},
        "disclosures": {symbol: DISCLOSURES[symbol] for symbol in symbols if symbol in DISCLOSURES},
    }


store = IntradayStore()
