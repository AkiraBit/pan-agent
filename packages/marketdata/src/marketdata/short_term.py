"""Bounded Eastmoney market-level reads; never fall back to synthetic boards.

Change is percent, amount is CNY, volume is lots (100 shares). Source timestamps
are vendor-reported, not a guarantee of exchange latency. Pool scope excludes
ST, STAR and certain newly listed stocks according to the provider's definition.
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from marketdata.http import market_get

TZ = ZoneInfo("Asia/Shanghai")
UNIVERSE = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
POOLS = {"up": "getTopicZTPool", "down": "getTopicDTPool",
         "broken": "getTopicZBPool", "yesterday": "getYesterdayZTPool"}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


@dataclass
class Batch:
    scope: str
    rows: list[dict] = field(default_factory=list)
    expected: int | None = None
    status: str = "unavailable"
    reason: str = "request_failed"
    received_at: str = field(default_factory=lambda: datetime.now(TZ).isoformat())
    trade_date: str | None = None
    provider: str = "eastmoney"

    def metadata(self):
        result = asdict(self)
        result.pop("rows")
        result.update(count=len(self.rows), coverage=(len(self.rows) / self.expected
                      if self.expected else (1 if self.expected == 0 else None)))
        return result


def _get(url, params):
    return market_get(url, host_key="short-term.eastmoney", params=params,
                      headers={"User-Agent": "Mozilla/5.0"}, parse="json",
                      timeout=6, total_timeout=8, retries=0, min_interval_s=0.15)


def _page(fs, page):
    body = _get("https://push2delay.eastmoney.com/api/qt/clist/get", {
        "pn": page, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f12", "fs": fs, "fields": "f12,f14,f2,f3,f5,f6,f124"})
    data = body.get("data") if isinstance(body, dict) and body.get("rc") == 0 else None
    if not isinstance(data, dict) or not isinstance(data.get("total"), int):
        return None
    rows = data.get("diff")
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    if rows is None and data["total"] == 0:
        rows = []
    return (data["total"], rows) if isinstance(rows, list) else None


def quote_row(row):
    if not isinstance(row, dict) or not row.get("f12") or not row.get("f14"):
        return None
    stamp = number(row.get("f124"))
    return {"code": str(row["f12"]), "name": str(row["f14"]),
            "price": number(row.get("f2")), "change": number(row.get("f3")),
            "amount": number(row.get("f6")), "volume": number(row.get("f5")),
            "source_time": stamp if stamp and 946684800 < stamp < 4102444800 else None}


def quotes(scope="market", fs=UNIVERSE):
    batch, start = Batch(scope), time.monotonic()
    first = _page(fs, 1)
    if first is None:
        return batch
    total, raw = first
    batch.expected = total
    if total < 0 or total > 8000:
        batch.reason = "invalid_total"
        return batch
    complete = True
    with ThreadPoolExecutor(max_workers=4) as executor:
        for start_page in range(2, math.ceil(total / 100) + 1, 4):
            if time.monotonic() - start > 60:
                complete = False
                break
            pages = range(start_page, min(start_page + 4, math.ceil(total / 100) + 1))
            for result in executor.map(lambda p: _page(fs, p), pages):
                if result is None:
                    complete = False
                else:
                    complete = complete and result[0] == total
                    raw.extend(result[1])
    parsed = [quote_row(row) for row in raw]
    unique = {row["code"]: row for row in parsed if row}
    batch.rows = list(unique.values())
    complete = complete and len(unique) == len(raw) == total and None not in parsed
    batch.status = "complete" if complete else "partial"
    batch.reason = "ok" if complete else "incomplete_pages"
    batch.received_at = datetime.now(TZ).isoformat()
    return batch


def pool_clock(value):
    n = number(value)
    if n is None or n <= 0 or n != int(n):
        return None
    clock = str(int(n)).zfill(6)
    if len(clock) != 6 or int(clock[:2]) > 23 or int(clock[2:4]) > 59 or int(clock[4:]) > 59:
        return None
    return f"{clock[:2]}:{clock[2:4]}:{clock[4:]}"


def limit_pool(kind: str, day: str):
    batch = Batch(f"pool:{kind}", trade_date=day)
    body = _get(f"https://push2ex.eastmoney.com/{POOLS[kind]}", {
        "ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
        "Pageindex": 0, "pagesize": 10000,
        "sort": "zs:desc" if kind == "yesterday" else "fund:asc" if kind == "down" else "fbt:asc",
        "date": day.replace("-", "")})
    data = body.get("data") if isinstance(body, dict) and body.get("rc") == 0 else None
    if not isinstance(data, dict) or not isinstance(data.get("pool"), list):
        return batch
    if str(data.get("qdate")) != day.replace("-", ""):
        batch.reason = "date_mismatch"
        return batch
    total = data.get("tc")
    if not isinstance(total, int) or total < 0:
        batch.reason = "invalid_total"
        return batch
    batch.expected = total
    for row in data["pool"]:
        if not isinstance(row, dict) or not row.get("c") or not row.get("n"):
            continue
        batch.rows.append({"code": str(row["c"]), "name": str(row["n"]),
                           "change": number(row.get("zdp")),
                           "streak": number(row.get("lbc")),
                           "breaks": number(row.get("zbc")),
                           "previous_streak": number(row.get("ylbc")),
                           "first_time": pool_clock(row.get("fbt")), "last_time": pool_clock(row.get("lbt")),
                           "sealed_amount": number(row.get("fund")), "amount": number(row.get("amount")),
                           "turnover_rate": number(row.get("hs"))})
    codes = {row["code"] for row in batch.rows}
    complete = len(codes) == len(batch.rows) == len(data["pool"]) == total
    batch.status = "complete" if complete else "partial"
    batch.reason = "ok" if complete else "incomplete_pool"
    return batch
