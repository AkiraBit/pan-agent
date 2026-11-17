"""Normalized adapters for existing PanWatch views that did not use Engine."""

import logging
from datetime import date, datetime, time, timedelta

from marketdata.symbol import Symbol
from marketdata.fallback import Cooldown, InvalidRequest
from marketdata.types import Bar
from marketdata.vendors.fuyao import SHANGHAI, _number, _stock_code, _time

from . import fuyao_business

logger = logging.getLogger(__name__)
_cooldown = Cooldown()
INDEX_CODES = {"000001": "000001.SH", "000300": "000300.SH", "399001": "399001.SZ", "399006": "399006.SZ"}


def first(kind, loaders, *, market="CN"):
    """Configured order, with no substitution between unlike data contracts."""
    for provider in fuyao_business.providers(kind, market=market, available=loaders):
        loader = loaders.get(provider)
        key = (kind, market, provider)
        if loader is None or not _cooldown.available(key):
            continue
        try:
            result = loader()
            if result:
                _cooldown.succeeded(key)
                return result
        except InvalidRequest:
            raise
        except Exception as exc:
            _cooldown.failed(key, getattr(exc, "retry_after", 0))
            logger.debug("Market data source unavailable: %s/%s (%s)", kind, provider, type(exc).__name__)
    return None


def search(query: str, market: str, limit: int):
    markets = {"SH": "CN", "SZ": "CN", "BJ": "CN", "HK": "HK", "US": "US",
               "NASDAQ": "US", "NYSE": "US", "AMEX": "US"}
    data = fuyao_business.marketdata_read("get_meta_tickers_search", {"q": query, "limit": min(50, limit)})
    results = []
    for row in (data or {}).get("item", []):
        code, name = row.get("ticker"), row.get("name")
        exchange = markets.get(row.get("exchange"))
        if (exchange and (not market or exchange == market) and isinstance(code, str) and isinstance(name, str)
                and row.get("asset_type") in {"a-share", "hk-share", "us-share", "etf"}):
            results.append({"symbol": code, "name": name, "market": exchange})
    return results


def index_quotes(raw_codes: list[str], legacy):
    cn = [raw for raw in raw_codes if raw.startswith(("sh", "sz"))]
    overseas = [raw for raw in raw_codes if raw not in cn]
    tencent = overseas if overseas and fuyao_business.providers(
        "index_quote", market="HK", available={"tencent"}) else []
    cn_provider = fuyao_business.providers("index_quote", available={"tencent", "fuyao"}) if cn else []
    if cn_provider == ["tencent"]:
        tencent = cn + tencent
    output = []
    if tencent:
        try:
            output.extend(legacy(tencent) or [])
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            logger.debug("Index quotes unavailable: tencent (%s)", type(exc).__name__)
    if cn_provider == ["fuyao"]:
        requested = {f"{raw[2:]}.{raw[:2].upper()}" for raw in cn}
        try:
            data = fuyao_business.marketdata_read("get_a_share_index_prices_snapshot", {"thscodes": ",".join(sorted(requested))})
            output.extend({"symbol": row["thscode"].split(".")[0], "current_price": _number(row.get("last_price")),
                           "change_pct": _number(row.get("price_change_ratio_pct")),
                           "change_amount": _number(row.get("price_change")), "prev_close": _number(row.get("prev_price")),
                           "source": "fuyao"} for row in (data or {}).get("item", [])
                          if row.get("thscode") in requested and _number(row.get("last_price")))
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            logger.debug("Index quotes unavailable: fuyao (%s)", type(exc).__name__)
    return output


def index_klines(code: str, days: int):
    thscode = INDEX_CODES.get(code, code)
    if not thscode.endswith((".SH", ".SZ", ".TI")):
        return []
    end = datetime.now(SHANGHAI)
    start = end - timedelta(days=min(days * 2 + 10, 1824))
    data = fuyao_business.marketdata_read("get_a_share_index_prices_historical", {
        "thscode": thscode, "interval": "1d", "start": int(start.timestamp() * 1000), "end": int(end.timestamp() * 1000),
    })
    bars = []
    for row in (data or {}).get("item", []):
        at = _time(row.get("date_ms"))
        prices = {field: _number(row.get(f"{field}_price")) for field in ("open", "close", "high", "low")}
        if at and all(v is not None and v > 0 for v in prices.values()):
            bars.append(Bar(date=at.date().isoformat(), **prices, volume=_number(row.get("volume")) or 0,
                            turnover=_number(row.get("turnover")), source="fuyao"))
    return sorted(bars, key=lambda b: b.date)[-days:]


def stock_code(code: str) -> str | None:
    return _stock_code(Symbol.parse(code, "CN"))


def open_days(start: date, end: date) -> set[date]:
    data = fuyao_business.marketdata_read("get_a_share_calendar_trading_days", {
        "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d"),
    })
    result = set()
    for row in (data or {}).get("item", []):
        parsed = datetime.strptime(row["date"], "%Y%m%d").date()
        if not start <= parsed <= end:
            raise ValueError("Unexpected dates from Fuyao calendar")
        result.add(parsed)
    return result


def pool_operation(kind: str):
    name = {"up": "limit_up_pool", "down": "limit_down_pool", "broken": "limit_break_pool"}.get(kind)
    return "get_a_share_special_data_" + name if name else None


def pool(kind: str, trade_date: str):
    from marketdata.short_term import Batch

    operation = pool_operation(kind)
    if operation is None:
        return None  # Yesterday's winners at today's prices use a different contract.
    day = date.fromisoformat(trade_date)
    args = {"date_ms": int(datetime.combine(day, time.min, SHANGHAI).timestamp() * 1000), "size": 200}
    found = {}
    expected = None
    for page in range(1, 5):
        data = fuyao_business.marketdata_read(operation, {**args, "page": page}) or {}
        pagination = data.get("pagination") or {}
        total = pagination.get("total")
        if type(total) is not int or total < 0 or (expected is not None and total != expected):
            return None
        expected = total
        for row in data.get("item") or []:
            code, name = row.get("ticker"), row.get("name")
            if not isinstance(code, str) or not name:
                continue
            found[code] = {
                "code": code, "name": name, "change": _number(row.get("price_change_ratio_pct")),
                "streak": _number(row.get("continue_day_cnt")), "breaks": _number(row.get("open_times")),
                "previous_streak": None, "first_time": row.get("limit_up_time") or row.get("first_limit_time") or row.get("first_seal_time"),
                "last_time": row.get("last_limit_time") or row.get("last_seal_time"),
                "sealed_amount": _number(row.get("seal_money")), "amount": _number(row.get("turnover")),
                "turnover_rate": _number(row.get("turnover_ratio_pct")),
            }
        if len(found) >= expected:
            break
    complete = len(found) == expected
    return Batch(f"pool:{kind}", rows=list(found.values()), expected=expected, provider="fuyao",
                 trade_date=trade_date, status="complete" if complete else "partial",
                 reason="ok" if complete else "incomplete_pool")
