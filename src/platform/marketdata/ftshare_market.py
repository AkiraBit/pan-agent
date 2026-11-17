"""Translate verified FTShare operations to the normalized market-data contracts."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import math
import re
import time

import httpx

from marketdata.fallback import InvalidRequest, SourceFailure
from marketdata.types import Bar, Quote

from . import ftshare_rest

CN = ZoneInfo("Asia/Shanghai")
EXCHANGE = {"sh": "XSHG", "sz": "XSHE", "bj": "BJSE"}
INDEX_EXCHANGE = {"000001": "SH", "000300": "SH", "399001": "SZ", "399006": "SZ"}


def client(key, timeout):
    return httpx.Client(headers={"FTSHARE_API_KEY": key, "Accept": "application/json"},
                        timeout=timeout, follow_redirects=False)


def data(operation, params, *, timeout=5):
    from src.platform.persistence.database import SessionLocal

    op = ftshare_rest.OPERATIONS[operation]
    checked = ftshare_rest.validate(op, {"params": params})
    with SessionLocal() as db:
        try:
            key = ftshare_rest.read_key(db)
        except ftshare_rest.CredentialUnavailable as exc:
            raise SourceFailure(str(exc), retry_after=60) from None
    try:
        # Only call paths registered in the versioned catalog.
        with client(key, max(0.2, min(float(timeout), 5))) as http:
            with http.stream(op["method"], ftshare_rest.ORIGIN + op["variants"][0]["path"],
                             params=checked["params"]) as response:
                if response.status_code == 429:
                    try:
                        delay = float(response.headers.get("Retry-After", "30"))
                    except ValueError:
                        delay = 30
                    raise SourceFailure("FTShare rate limited", retry_after=delay if math.isfinite(delay) else 30)
                if response.status_code in (401, 403):
                    raise SourceFailure("FTShare endpoint not authorized", retry_after=60)
                if response.status_code != 200:
                    raise SourceFailure(f"FTShare HTTP {response.status_code}")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > ftshare_rest.MAX_RESPONSE_BYTES:
                        raise SourceFailure("FTShare result exceeds size limit")
                payload = json.loads(raw)
    except (httpx.HTTPError, ValueError, RecursionError):
        raise SourceFailure("FTShare connection or response invalid") from None
    code = payload.get("code") if isinstance(payload, dict) else None
    if code in (401, 403):
        raise SourceFailure("FTShare endpoint not authorized", retry_after=60)
    if code == 429:
        raise SourceFailure("FTShare rate limited", retry_after=30)
    if type(code) is not int or code not in (0, 200):
        raise SourceFailure("FTShare returned an unsuccessful business status")
    return payload.get("data")


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def stamp(value):
    if type(value) is not int:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, CN)
    except (ValueError, OSError, OverflowError):
        return None


def chinese_code(symbol):
    if not re.fullmatch(r"[0-9]{6}", symbol.code):
        return None
    return symbol.code + "." + EXCHANGE[symbol.to_tencent()[:2]]


class FtshareQuoteVendor:
    supports_markets = {"CN"}

    def fetch(self, symbols, config):
        codes = {code: sym.code for sym in symbols if (code := chinese_code(sym))}
        result = []
        deadline = time.monotonic() + config.get("_timeout", 5)
        for start in range(0, len(codes), 100):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            batch = list(codes)[start:start + 100]
            payload = data("stock_daec_stocks", {"page": 1, "page_size": len(batch),
                "filter": "symkey IN " + json.dumps(batch, separators=(",", ":"))}, timeout=remaining)
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise SourceFailure("FTShare quote payload has no item list")
            for row in payload["items"]:
                if not isinstance(row, dict) or row.get("symbol") not in batch:
                    continue
                price, observed = number(row.get("close")), stamp(row.get("ts_millis"))
                # Without exchange time this is not a verified live quote.
                if price is None or price <= 0 or observed is None:
                    continue
                change, rate = number(row.get("change_rate")), number(row.get("turnover_rate"))
                result.append(Quote(symbol=codes[row["symbol"]], market="CN", current_price=price,
                    name=str(row.get("name") or ""), prev_close=number(row.get("prev_close")),
                    open_price=number(row.get("open")), high_price=number(row.get("high")), low_price=number(row.get("low")),
                    change_amount=number(row.get("change")), change_pct=None if change is None else change * 100,
                    turnover_rate=None if rate is None else rate * 100, volume=number(row.get("volume")),
                    turnover=number(row.get("turnover")), quote_date=observed.date(), source_timestamp=observed,
                    source="ftshare"))
        return result


def _bars(operation, code, days, *, adjust, timeout=5):
    if not 1 <= days <= 240:
        return []
    end = datetime.now(CN)
    start = end - timedelta(days=350)
    payload = data(operation, {"symbol": code, "interval_unit": "day", "adjust_kind": adjust,
        "since_ts_millis": str(int(start.timestamp() * 1000)), "until_ts_millis": str(int(end.timestamp() * 1000)),
        "limit": days}, timeout=timeout)
    if not isinstance(payload, list):
        raise SourceFailure("FTShare daily bar payload has no series")
    bars = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        when = stamp(row.get("ts_millis"))
        prices = {field: number(row.get(field)) for field in ("open", "close", "high", "low")}
        if not when or not start.date() <= when.date() <= end.date() or not all(x is not None and x > 0 for x in prices.values()):
            continue
        if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]):
            continue
        day = when.date().isoformat()
        if day in bars:
            raise SourceFailure("FTShare duplicate daily bar")
        bars[day] = Bar(date=day, **prices, volume=number(row.get("volume")) or 0,
                        turnover=number(row.get("turnover")), source="ftshare")
    return [bars[day] for day in sorted(bars)][-days:]


class FtshareKlineVendor:
    supports_markets = {"CN"}

    def fetch(self, symbols, config):
        if not symbols or not (code := chinese_code(symbols[0])):
            return []
        return _bars("stock_candlesticks", code, int(config["days"]), adjust="forward", timeout=config.get("_timeout", 5))


def index_bars(code, days):
    symbol = f"{code}.{INDEX_EXCHANGE[code]}" if code in INDEX_EXCHANGE else code
    if not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", symbol):
        return []
    return _bars("index_candlesticks", symbol, days, adjust="none")


def open_days(market, start, end):
    if market not in {"CN", "HK"}:
        raise InvalidRequest("FTShare calendar supports CN and HK")
    payload = data("trading_calendar", {"market": market.lower(),
        "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")})
    if (not isinstance(payload, dict) or payload.get("market") != market.lower()
            or str(payload.get("start_date")) != start.strftime("%Y%m%d")
            or str(payload.get("end_date")) != end.strftime("%Y%m%d") or not isinstance(payload.get("trade_dates"), list)):
        raise SourceFailure("FTShare calendar did not confirm the requested window")
    try:
        days = {datetime.strptime(str(raw), "%Y%m%d").date() for raw in payload["trade_dates"]}
    except ValueError:
        raise SourceFailure("FTShare calendar returned invalid dates") from None
    if not all(start <= day <= end for day in days):
        raise SourceFailure("FTShare calendar returned dates outside the requested window")
    return days
