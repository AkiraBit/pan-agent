"""Supported test inputs for the public website data adapters."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from marketdata.registry import VENDOR_CLASSES_BY_TYPE
from marketdata.symbol import Symbol

DEFAULT_TEST_SYMBOLS_BY_MARKET = {
    "CN": ("600519", "601127"), "HK": ("00700", "00386"), "US": ("AAPL", "NVDA"),
}
MARKET_WIDE = {"flash_news", "dragon_tiger", "northbound"}


def completed_trade_date(now=None):
    from src.platform.scheduling.trading_calendar import is_trading_day

    now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    day = now.date() - timedelta(days=int((now.hour, now.minute) < (15, 15)))
    return next((candidate.isoformat() for n in range(20)
                 if is_trading_day("CN", candidate := day - timedelta(days=n))), None)


def number(key, default, minimum, maximum, *, wire=None):
    return dict(key=key, type="integer", default=default, minimum=minimum, maximum=maximum, wire=wire)


def spec(provider, kind):
    if provider not in {"eastmoney", "eastmoney_news", "tencent", "sina", "cls"}:
        return None
    adapter = VENDOR_CLASSES_BY_TYPE.get(kind, {}).get(provider)
    if adapter is None and (kind, provider) != ("chart", "eastmoney"):
        return None
    markets = set(getattr(adapter, "supports_markets", ()) or ("CN",))
    if kind == "capital_flow":
        markets = {"CN"}
    symbol_config = None
    if kind not in MARKET_WIDE:
        defaults = tuple(code for m, codes in DEFAULT_TEST_SYMBOLS_BY_MARKET.items() if m in markets for code in codes)
        maximum = 1 if kind == "chart" else (
            5 if kind in {"fundamentals", "margin", "shareholders", "dividend"} else 10)
        symbol_config = dict(markets=sorted(markets), maximum=maximum, examples=list(defaults[:maximum]))

    fields = []
    if kind == "flash_news":
        fields.append(number("limit", 20, 1, 50, wire={"cls": "rn", "sina": "page_size", "eastmoney": "pageSize"}[provider]))
    elif kind == "kline":
        fields.append(number("count", 30, 1, adapter._MAX_COUNT if provider == "tencent" else 1000))
    elif kind == "news":
        # The Eastmoney announcement reader has a minimum 72-hour lookback.
        hours = 72 if provider == "eastmoney" else 2
        fields.append(number("lookback_hours", hours, 72 if provider == "eastmoney" else 1, 720))
    elif kind == "events":
        fields.append(number("lookback_days", 365, 1, 365))
        if provider == "eastmoney":
            fields.append(number("page_size", 100, 1, 100, wire="page_size"))
    elif kind == "dragon_tiger":
        fields.append(dict(key="test_date", type="date", default=completed_trade_date(), wire=None))
    elif kind == "chart":
        fields.append(number("extra_wait_ms", 2000, 0, 10000))
    return {"symbols": symbol_config, "fields": fields}


def _normalize_code(raw, symbol_config):
    value = raw.strip().upper()
    market = Symbol.parse(value).market.value
    patterns = {"CN": r"[0-9]{6}", "HK": r"[0-9]{5}", "US": r"[A-Z][A-Z0-9.-]{0,14}"}
    if market not in symbol_config["markets"] or not re.fullmatch(patterns[market], value):
        raise ValueError(f"此测试不支持该证券代码：{raw}")
    return value


def normalize_symbols(symbol_config, raw, *, strict=True):
    if not symbol_config:
        return []
    if raw is not None and not isinstance(raw, (list, tuple)):
        raise ValueError("证券代码必须为列表。")
    result = []
    for value in raw or []:
        try:
            result.append(_normalize_code(value, symbol_config))
        except (AttributeError, ValueError):
            if strict:
                raise ValueError(f"请检查测试证券代码：{value}") from None
    result = list(dict.fromkeys(result))
    maximum = symbol_config["maximum"]
    if strict and len(result) > maximum:
        raise ValueError(f"此测试最多支持 {maximum} 个证券代码。")
    return (result or symbol_config["examples"])[:maximum]


def validate_params(fields, values):
    definitions = {f["key"]: f for f in fields}
    if not isinstance(values, dict) or values.keys() - definitions.keys():
        raise ValueError("包含此测试不支持的参数。")
    out = {}
    for key, val in values.items():
        if val is None or val == "":
            continue
        field = definitions[key]
        kind = field["type"]
        if kind == "integer":
            if type(val) is int or (isinstance(val, str) and re.fullmatch(r"[0-9]{1,8}", val)):
                val = int(val)
                if field["minimum"] <= val <= field["maximum"]:
                    out[key] = val
                    continue
        elif kind == "date" and isinstance(val, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", val):
            try:
                out[key] = date.fromisoformat(val).isoformat()
                continue
            except ValueError:
                pass
        raise ValueError(f"测试参数 {key} 格式或取值无效。")
    return out


def describe(source):
    settings = spec(source.provider, source.type)
    if not settings:
        return None
    cfg = source.config or {}
    fields = settings["fields"]
    stored = cfg.get("test_params")
    if not isinstance(stored, dict):
        stored = {f["key"]: cfg.get(f["key"]) for f in fields} if source.type in {"dragon_tiger", "chart"} else {}
    settings["values"] = {}
    for field in fields:
        try:
            settings["values"].update(validate_params(fields, {field["key"]: stored.get(field["key"])}))
        except ValueError:
            pass  # Older configs may carry test values from a generic JSON editor.
    settings["test_symbols"] = normalize_symbols(settings["symbols"], source.test_symbols, strict=False)
    return settings


def probe_params(settings):
    return {**{f["key"]: f["default"] for f in settings["fields"]}, **settings["values"]}
