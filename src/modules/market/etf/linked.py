"""Linked ETF turnover, dated constituent baskets and durable minute observations."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from math import fsum
from statistics import median

from sqlalchemy import select

from src.modules.market.etf import intraday, market_stats, prices
from src.modules.market.etf.models import EtfAnalysisCache, EtfAnalysisMinute
from src.platform.marketdata import tushare_market
from src.platform.marketdata.tushare_market import TushareFailure
from src.platform.persistence.database import SessionLocal

GROUPS = {
    "csi300": ("000300.SH", ("510300.SH", "510310.SH", "510330.SH", "159919.SZ")),
    "sse50": ("000016.SH", ("510050.SH",)),
    "csi500": ("000905.SH", ("510500.SH", "159922.SZ")),
    "csi1000": ("000852.SH", ("159845.SZ", "512100.SH", "560010.SH", "159633.SZ")),
    "growth": ("399006.SZ", ("159915.SZ", "159952.SZ", "159949.SZ")),
    "star": ("000688.SH", ("588000.SH", "588080.SH")),
    "a500": ("000510.SH", ("512050.SH", "563360.SH", "159338.SZ", "159352.SZ", "159361.SZ")),
    "sse": ("000001.SH", ("510210.SH",)),
}
BOARDS = ("all", "main", "growth", "star", "beijing")


def board(symbol):
    return "beijing" if symbol.endswith(".BJ") else "star" if symbol.startswith("688") else "growth" if symbol.startswith("3") else "main"


def distribution(values):
    values = list(values)
    return {"up": sum(v > 0 for v in values), "down": sum(v < 0 for v in values),
            "flat": sum(v == 0 for v in values), "total": len(values),
            "median": median(values) if values else None}


def _cached(day, key):
    with SessionLocal() as db:
        row = db.get(EtfAnalysisCache, (day.isoformat(), key))
        return row.payload if row else None


def _save_cache(day, key, payload):
    with SessionLocal.begin() as db:
        db.merge(EtfAnalysisCache(trade_date=day.isoformat(), key=key, payload=payload))


def save_observation(day, minute, returns, *, source="snapshot", complete=True, sessions=None):
    """Keep现场 observations authoritative; partial reconstructions never imply full-market coverage."""
    with (sessions or SessionLocal).begin() as db:
        row = db.get(EtfAnalysisMinute, (day.isoformat(), minute))
        if row and row.payload.get("source") == "snapshot":
            return
        payload = {"returns": {**(row.payload.get("returns", {}) if row else {}), **returns}, "source": source}
        if complete:
            payload["boards"] = {key: distribution(v for code, v in returns.items() if key == "all" or board(code) == key)
                                 for key in BOARDS}
        elif row and row.payload.get("boards"):
            payload["boards"] = row.payload["boards"]
        db.merge(EtfAnalysisMinute(trade_date=day.isoformat(), minute=minute, payload=payload))


def capture_observation(day, minute, rows, *, sessions=None):
    selected = {}
    for row in rows:
        code, stamp = row.get("ts_code"), row.get("trade_time")
        if (not isinstance(code, str) or not market_stats.STOCK_CODE.fullmatch(code)
                or not isinstance(stamp, str) or stamp[:10] != day.isoformat() or stamp[11:16] > minute):
            continue
        try:
            previous = intraday.number(row.get("pre_close"), positive=True)
            close = intraday.number(row.get("close"), positive=True)
            intraday.number(row.get("vol"), positive=True)
        except TushareFailure:
            continue
        if code not in selected or stamp > selected[code][0]:
            selected[code] = (stamp, round(close / previous - 1, 8))
    if selected:
        save_observation(day, minute, {code: value for code, (_, value) in selected.items()}, sessions=sessions)


def observations(day, through):
    with SessionLocal() as db:
        rows = db.scalars(select(EtfAnalysisMinute).where(
            EtfAnalysisMinute.trade_date == day.isoformat(), EtfAnalysisMinute.minute <= through))
        return {row.minute: row.payload for row in rows}


def grouped_turnover(day):
    saved = intraday.store._read(day)
    members = saved.get("members", [])
    parts = saved.get("parts", {})
    basis = intraday.baseline_basis(day, saved)
    historical, _ = intraday.store._read_baseline_inputs([date.fromisoformat(d) for d in basis["days"]]) if basis else ({}, {})
    result = []
    for key, (index, funds) in GROUPS.items():
        funds = [code for code in funds if code in members]
        if not funds:
            continue
        points = {}
        for minute in intraday.MINUTES:
            values = [parts.get(code, {}).get("data", {}).get(minute) for code in funds]
            points[minute] = fsum(values) if all(v is not None for v in values) else None
        baseline = None
        if historical and all(intraday.full_session(historical[d].get(code, {})) for d in historical for code in funds):
            cumulative = 0.0
            baseline = {}
            for minute in intraday.MINUTES:
                cumulative += fsum(historical[d][code]["data"][minute] for d in historical for code in funds) / len(historical)
                baseline[minute] = cumulative
        result.append({"id": key, "index": index, "symbols": funds, "points": points, "baseline": baseline})
    return result


_locks = tuple(asyncio.Lock() for _ in range(16))


async def basket(day, group):
    key = f"basket:v2:{group}"
    async with _locks[hash((day, group)) % len(_locks)]:
        saved = await asyncio.to_thread(_cached, day, key)
        if saved:
            return saved
        index, funds = GROUPS[group]
        symbol = funds[0]
        operation = "etf_sh_cons" if symbol.endswith(".SH") else "etf_sz_cons"
        rows = await tushare_market.rows(operation, {"ts_code": symbol, "trade_date": day.strftime("%Y%m%d")})
        names = {}
        for row in rows:
            code = row.get("con_code")
            if row.get("trade_date") != day.strftime("%Y%m%d") or row.get("ts_code") != symbol:
                continue
            if isinstance(code, str) and market_stats.STOCK_CODE.fullmatch(code):
                # Keep listed constituents even when creation-unit rounding produces zero quantity.
                try:
                    intraday.number(row.get("qty"))
                except TushareFailure:
                    continue
                names[code] = row.get("con_name") or code
        if not names:
            raise TushareFailure("unavailable")
        weights, weights_date = {}, None
        try:
            rows = await tushare_market.rows("index_weight", {"index_code": index,
                "start_date": (day - timedelta(days=62)).strftime("%Y%m%d"), "end_date": day.strftime("%Y%m%d")})
            dates = [row.get("trade_date") for row in rows if row.get("index_code") == index
                     and isinstance(row.get("trade_date"), str) and row["trade_date"] <= day.strftime("%Y%m%d")]
            if dates:
                weights_date = max(dates)
                weights = {row["con_code"]: float(row["weight"]) / 100 for row in rows
                           if row.get("trade_date") == weights_date and row.get("con_code") in names and row.get("weight") is not None}
        except (TushareFailure, ValueError, TypeError):
            pass
        saved = {"date": day.isoformat(), "group": group, "symbol": symbol, "names": names,
                 "weights": weights, "weights_date": weights_date}
        await asyncio.to_thread(_save_cache, day, key, saved)
        return saved


async def benchmarks(day):
    async def one(group):
        code = GROUPS[group][0]
        quote = await prices.index_store.load(day, code)
        previous = await asyncio.to_thread(_cached, day, f"reference:{code}")
        if previous is None:
            prior = intraday.adjacent(day, -1, day)
            if prior:
                try:
                    rows = await tushare_market.rows("index_daily", {"ts_code": code, "trade_date": prior.replace("-", "")},
                                                     "ts_code,trade_date,close")
                    value = next((intraday.number(row["close"], positive=True) for row in rows
                                  if row.get("ts_code") == code and row.get("trade_date") == prior.replace("-", "")), None)
                    if value is not None:
                        previous = {"close": value, "date": prior}
                        await asyncio.to_thread(_save_cache, day, f"reference:{code}", previous)
                except TushareFailure:
                    pass
        return {"group": group, "symbol": code, "closes": quote["closes"],
                "previous_close": previous["close"] if previous else None, "issue": quote.get("issue")}
    return await asyncio.gather(*(one(group) for group in ("csi300", "csi1000", "growth")))


async def load(day):
    through = market_stats.latest_closed_minute(day, intraday.now_cn()) or ""
    groups, quotes, recorded = await asyncio.gather(asyncio.to_thread(grouped_turnover, day), benchmarks(day),
                                                  asyncio.to_thread(observations, day, through))
    return {"date": day.isoformat(), "groups": groups, "benchmarks": quotes,
            "backfill": await replay.status(day, "all"),
            "boards": {key: {minute: {**entry["boards"][key], "source": entry["source"]}
                             for minute, entry in recorded.items() if entry.get("boards", {}).get(key)} for key in BOARDS}}


async def components(day, group, minute):
    try:
        selected = await basket(day, group)
    except TushareFailure as exc:
        return {"date": day.isoformat(), "group": group, "minute": minute, "issue": exc.code, "total": 0,
                "covered": 0, "up": 0, "down": 0, "flat": 0, "median": None, "leaders": [], "laggards": []}
    recorded = await asyncio.to_thread(observations, day, minute)
    entry = recorded.get(minute, {})
    returns = entry.get("returns", {})
    members = selected["names"]
    values = {code: returns[code] for code in members if code in returns}
    weights = selected["weights"]
    def item(code):
        return {"symbol": code, "name": members[code], "change": values[code],
                "contribution": values[code] * weights[code] if code in weights else None}
    weighted = bool(values) and values.keys() <= weights.keys()
    ordered = sorted(values, key=lambda code: values[code] * weights[code] if weighted else values[code], reverse=True)
    return {"date": day.isoformat(), "group": group, "minute": minute, "issue": None,
            **distribution(values.values()), "total": len(members), "covered": len(values),
            "source": entry.get("source"), "weights_date": selected.get("weights_date") if weighted else None,
            "leaders": [item(code) for code in ordered if values[code] > 0][:3],
            "laggards": [item(code) for code in reversed(ordered) if values[code] < 0][:3]}


class ComponentReplay:
    def __init__(self):
        self.task = None
        self.key = None
        self.progress = None

    async def start(self, day, group):
        if self.task and not self.task.done():
            return "running" if self.key == (day, group) else "busy"
        through = market_stats.latest_due(day, intraday.now_cn())
        if not through:
            return "nothing_to_fill"
        selected = {"names": {}} if group == "all" else await basket(day, group)
        if self.task and not self.task.done():
            return "running" if self.key == (day, group) else "busy"
        self.key = (day, group)
        self.progress = {"status": "running", "processed": 0, "total": len(selected["names"]), "through": through}
        self.task = asyncio.create_task(self.run(day, group, selected, through))
        return "running"

    async def run(self, day, group, selected, through):
        from src.modules.market.etf import breadth_replay
        import time
        gate = asyncio.Lock()
        next_at = 0.0
        async def fetch(op, params, fields=""):
            nonlocal next_at
            async with gate:
                await asyncio.sleep(max(0, next_at - time.monotonic()))
                next_at = time.monotonic() + 1.1
            return await tushare_market.rows(op, params, fields)
        try:
            reference = await breadth_replay._reference(day, fetch)
            if group == "all":
                selected = {"names": reference}
            cached = await asyncio.to_thread(breadth_replay._cached_bars, day)
            minutes = tuple(m for m in intraday.MINUTES if m <= through)
            pending = [code for code in selected["names"] if code in reference and not set(minutes) <= cached.get(code, {}).keys()]
            self.progress["total"] = len(selected["names"].keys() & reference.keys())
            self.progress["processed"] = self.progress["total"] - len(pending)
            for code in pending:
                values = await breadth_replay._bars(day, code, through, fetch, allow_partial=True)
                cached[code] = {**cached.get(code, {}), **values}
                await asyncio.to_thread(breadth_replay._save_bars, day, {code: cached[code]})
                self.progress["processed"] += 1
            selected_reference = {code: reference[code] for code in selected["names"] if code in reference}
            selected_bars = {code: cached[code] for code in selected_reference if code in cached}
            ready = breadth_replay._MinuteCoverage(selected_reference, selected_bars, minutes).ready()
            await asyncio.to_thread(save_reconstructed, day, reference, selected_bars,
                                    tuple(ready) if group == "all" else minutes, group == "all")
            self.progress["status"] = "complete" if len(ready) == len(minutes) else "partial"
            if self.progress["status"] == "partial":
                self.progress["reason"] = "missing_minutes"
        except TushareFailure as exc:
            self.progress.update(status="partial", reason=exc.code)
        finally:
            await asyncio.to_thread(_save_cache, day, f"replay:{group}", self.progress.copy())

    async def status(self, day, group):
        if self.key == (day, group):
            return self.progress
        saved = await asyncio.to_thread(_cached, day, f"replay:{group}")
        return {**saved, "status": "partial"} if saved and saved.get("status") == "running" else saved

    async def shutdown(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


def save_reconstructed(day, reference, bars, minutes, complete=True, *, sessions=None):
    """A missing bar breaks continuity; zero-volume bars carry the last traded price."""
    if not minutes:
        return
    values = {minute: {} for minute in minutes}
    for code, series in bars.items():
        if code not in reference:
            continue
        price = None
        for minute in intraday.MINUTES:
            if minute > minutes[-1]:
                break
            if minute not in series:
                price = None
            elif series[minute] is not None:
                price = series[minute]
            if price is not None and minute in values:
                values[minute][code] = round(price / reference[code] - 1, 8)
    for minute, returns in values.items():
        if returns:
            save_observation(day, minute, returns, source="backfill", complete=complete, sessions=sessions)


replay = ComponentReplay()
