"""ETF and exchange index directory search and cached minute closes."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from unicodedata import normalize

from src.modules.market.etf import intraday
from src.modules.market.etf.models import EtfPriceSession, EtfTushareUniverse, IndexPriceSession
from src.platform.marketdata.tushare_market import TushareFailure
from src.platform.persistence.database import SessionLocal

CATALOG_KEY = "tushare-etf-price-catalog-v1"
SYMBOL = re.compile(r"\d{6}\.(SH|SZ)")


def _term(text):
    return normalize("NFKC", text).strip().casefold()


def _missing_ranges(minutes, values):
    start = end = None
    for minute in minutes:
        if minute not in values:
            start = start or minute
            end = minute
        elif start is not None:
            yield start, end
            start = end = None
    if start is not None:
        yield start, end


class EtfPriceStore:
    def __init__(self, kind="etf"):
        self.kind = kind
        self._model = IndexPriceSession if kind == "index" else EtfPriceSession
        self._catalog_key = "tushare-exchange-index-price-catalog-v1" if kind == "index" else CATALOG_KEY
        self._latest_operation = "rt_idx_min" if kind == "index" else "rt_etf_min"
        self._archive_operation = "idx_mins" if kind == "index" else "etf_mins"
        self._catalog_lock = asyncio.Lock()
        self._locks = tuple(asyncio.Lock() for _ in range(32))
        self._catalog_retry = 0
        self._catalog_issue = "unavailable"

    def _read_catalog(self):
        with SessionLocal() as db:
            row = db.get(EtfTushareUniverse, self._catalog_key)
            return (row.updated_on, row.payload) if row else ("", {})

    def _save_catalog(self, today, catalog):
        with SessionLocal() as db:
            db.merge(EtfTushareUniverse(key=self._catalog_key, updated_on=today.isoformat(), payload=catalog))
            db.commit()

    def _read(self, day, symbol):
        with SessionLocal() as db:
            row = db.get(self._model, (day.isoformat(), symbol))
            return row.payload if row else {}

    def _save(self, day, symbol, payload):
        with SessionLocal() as db:
            db.merge(self._model(trade_date=day.isoformat(), symbol=symbol, payload=payload))
            db.commit()

    async def _catalog_rows(self):
        if self.kind == "index":
            markets = await asyncio.gather(*(
                intraday.store._query("index_basic", {"market": market}, "ts_code,name,list_date")
                for market in ("SSE", "SZSE")
            ))
            return [row for market in markets for row in market]
        return await intraday.store._query("etf_basic", {"list_status": "L"}, "ts_code,csname,list_date,list_status")

    async def _catalog(self):
        async with self._catalog_lock:
            now = intraday.now_cn()
            today = now.date()
            updated, cached = await asyncio.to_thread(self._read_catalog)
            if cached and (updated >= (today - timedelta(days=6)).isoformat() or now.timestamp() < self._catalog_retry):
                return cached
            if now.timestamp() < self._catalog_retry:
                raise TushareFailure(self._catalog_issue)
            try:
                rows = await self._catalog_rows()
                catalog = {}
                for row in rows:
                    code, name = row.get("ts_code"), row.get("name" if self.kind == "index" else "csname")
                    if not isinstance(code, str) or not SYMBOL.fullmatch(code) or not isinstance(name, str) or not name.strip():
                        continue
                    if self.kind == "etf" and row.get("list_status") != "L":
                        continue
                    try:
                        listed = datetime.strptime(row.get("list_date"), "%Y%m%d").date().isoformat()
                    except (TypeError, ValueError):
                        if self.kind == "etf":
                            continue
                        listed = None
                    catalog[code] = {"name": name.strip(), "listed": listed}
                if not catalog:
                    raise TushareFailure("unavailable")
            except TushareFailure as err:
                self._catalog_retry = now.timestamp() + max(30, err.retry_after)
                self._catalog_issue = err.code
                if cached:
                    return cached
                raise
            await asyncio.to_thread(self._save_catalog, today, catalog)
            return catalog

    async def search(self, query, *, include_all=False):
        def item(code, name):
            row = {"symbol": code, "name": name}
            return {**row, "kind": "index"} if self.kind == "index" else row

        query = _term(query)
        if not query and not include_all:
            return {"items": [], "issue": None}
        try:
            catalog = await self._catalog()
        except TushareFailure as err:
            return {"items": [], "issue": err.code}
        if not query:
            return {"items": [item(code, catalog[code]["name"]) for code in sorted(catalog)], "issue": None}
        matches = []
        for code, entry in catalog.items():
            name = _term(entry["name"])
            code_key = _term(code)
            if query in (code_key, code_key.split(".")[0], name):
                priority = 0
            elif code_key.startswith(query) or name.startswith(query):
                priority = 1
            elif query in name:
                priority = 2
            else:
                continue
            matches.append((priority, code, entry["name"]))
        ordered = sorted(matches)
        return {"items": [item(code, name) for _, code, name in (ordered if include_all else ordered[:24])], "issue": None}

    async def _minute_closes(self, operation, params, day, symbol, *, live):
        fields = "" if live else "ts_code,trade_time,close"
        rows = await intraday.store._query(operation, params, fields)
        # Some exchange index feeds return two records for a closing minute.
        return intraday.minute_series(rows, day, symbol, "close", live=live, keep_first=self.kind == "index" and live)

    async def load(self, day, symbol):
        moment = intraday.now_cn()
        live = day == moment.date() and moment.time() < intraday.ARCHIVE_READY
        minutes = intraday.MINUTES if not live else tuple(m for m in intraday.MINUTES if m <= moment.strftime("%H:%M"))

        def response(values=None, issue=None):
            values = values or {}
            row = {"date": day.isoformat(), "symbol": symbol, "closes": values, "issue": issue,
                   "complete": bool(minutes) and all(minute in values for minute in minutes)}
            return {**row, "kind": "index"} if self.kind == "index" else row

        if not minutes or intraday.is_closed(day):
            return response()
        async with self._locks[hash((day, symbol)) % len(self._locks)]:
            saved = await asyncio.to_thread(self._read, day, symbol)
            values = saved.get("closes", {})
            missing = [m for m in minutes if m not in values]
            if not missing:
                return response(values)

            attempt = minutes[-1] if live else "archive"
            if (saved.get("attempt") == attempt or saved.get("issue") in intraday.HARD_FAILURES) and moment.timestamp() < saved.get("retry_at", 0):
                return response(values, saved.get("issue"))
            issue = None
            retry = intraday.LIVE_SLOT_RETRY if live else intraday.HISTORY_RETRY
            try:
                if not saved.get("validated"):
                    entry = (await self._catalog()).get(symbol)
                    if not entry:
                        return response(issue="unknown_index" if self.kind == "index" else "unknown_etf")
                    if entry["listed"] and day.isoformat() < entry["listed"]:
                        return response()
                    saved["validated"] = True

                if live:
                    params = {"ts_code": symbol, "freq": "1MIN"}
                    if values and missing == [minutes[-1]]:
                        try:
                            values.update(await self._minute_closes(self._latest_operation, params, day, symbol, live=True))
                        except TushareFailure as err:
                            if err.code not in {"source_disabled", "unavailable"}:
                                raise
                            values.update(await self._minute_closes(f"{self._latest_operation}_daily", params, day, symbol, live=True))
                    else:
                        values.update(await self._minute_closes(f"{self._latest_operation}_daily", params, day, symbol, live=True))
                else:
                    # Bound scattered upstream holes without requesting already cached ranges.
                    for start, end in list(_missing_ranges(minutes, values))[:4]:
                        result = await self._minute_closes(self._archive_operation, {
                            "ts_code": symbol, "freq": "1min",
                            "start_date": f"{day} {start}:00", "end_date": f"{day} {end}:00",
                        }, day, symbol, live=False)
                        values.update((minute, close) for minute, close in result.items() if start <= minute <= end)
            except TushareFailure as err:
                issue = err.code
                retry = max(retry, err.retry_after)
            await asyncio.to_thread(self._save, day, symbol, {
                "closes": values, "validated": saved.get("validated", False), "issue": issue, "attempt": attempt,
                "retry_at": intraday.now_cn().timestamp() + retry,
            })
            return response(values, issue)


store = EtfPriceStore()
index_store = EtfPriceStore("index")
