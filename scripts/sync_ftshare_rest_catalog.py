"""Build the local FTShare catalog from the provider's public documentation JSON."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
DOC = "https://market.ft.tech/gateway/doc"
INDEX = "pb8eizu3"
OUTPUT = ROOT / "src/platform/marketdata/ftshare_rest_catalog.json"
PATH = re.compile(r"/api/v[123]/[a-zA-Z0-9_/-]+")
TABLE = re.compile(r"(?<!\\)\|")
STOCK_LIST = "mdsj0xyo"
INPUT_CHOICES = {
    "futures_minutes": ("exactly_one", ("symbol", "symbols")),
    "convertible_bond_minute_candlesticks": ("exactly_one", ("symbol", "symbols")),
    "get_fund_manager": ("exactly_one", ("fund_code", "fund_manager")),
    "futures_nanhua_index_kline": ("at_least_one", ("code", "trade_date")),
}
DATE_PAIRS = {
    "hsi_daily_weight", "stock_unlock", "etf_net_value", "get_eastmoney_stock_flow",
    "get_eastmoney_etf_flow", "ths_all_board_kline", "ft_limit", "fut_settle", "index_fut_depth",
}
CHOICES = {
    ("get_stock_share", "date_type"): ("publish_date", "end_date"),
    ("get_price_change", "direction"): ("forward", "backward"),
    ("baidu_financial_calendar", "category"): ("economic", "ipo", "report_time", "trade_reminder"),
    ("eastmoney_rank", "market"): ("A", "HK", "US"),
    ("stock_market", "scope"): ("ChinaStock", "Xshg", "Xshe", "Bjse"),
    ("xueqiu_rank", "period"): ("7d", "total"),
    ("futures_kline", "interval"): ("daily", "weekly", "monthly", "quarterly"),
    ("futures_kline_batch", "interval"): ("daily", "weekly", "monthly", "quarterly"),
    ("futures_minutes", "interval"): ("1min", "5min", "15min", "30min", "60min"),
    ("market_stock_factor", "category"): ("quote", "valuation", "capital", "trend", "momentum", "volatility", "volume", "sentiment"),
    ("sge_spot_description_all", "category"): ("spot_full", "spot_forward", "spot_deferred"),
    ("market_v2_announcements_periodic_reports", "report_type"): ("annual", "semi_annual", "q1", "q3"),
    ("ths_hot_list", "list_type"): ("stock_hour", "stock_day", "stock_skyrocket", "etf", "bond", "hk", "usa", "fund", "future"),
    ("us_economic", "type"): ("ism-manufacturing", "ism-non-manufacturing", "nonfarm-payroll", "trade-balance",
        "unemployment-rate", "ppi-mom", "cpi-mom", "cpi-yoy", "core-cpi-mom", "core-cpi-yoy",
        "housing-starts", "existing-home-sales", "durable-goods-orders-mom", "cb-consumer-confidence",
        "gdp-yoy-preliminary", "fed-funds-rate-upper"),
}


def package_rows(text: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        for tier, cell in zip(("free", "basic"), TABLE.split(line)[1:-1]):
            match = re.fullmatch(rf"\s*\[([^\]]+)\]\({re.escape(DOC)}/p/([a-z0-9]+)\)\s*", cell)
            if match:
                rows.append((tier, *match.groups()))
    if Counter(row[0] for row in rows) != {"free": 168, "basic": 57} or len({row[2] for row in rows}) != 225:
        raise ValueError("Official plan table changed: review before updating the supported plans.")
    return rows


def field(text, label):
    return re.search(rf"^[-*] {label}[：:]\s*(.+)$", text, re.M)[1].strip()


def parameters(block):
    params = []
    for line in block.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in TABLE.split(line)[1:-1]]
        if len(cells) != 4 or cells[2] not in ("Y", "N"):
            continue
        name, kind, required, description = cells
        name = name.strip("`")
        item = {"name": name, "type": "boolean" if kind == "bool" else kind,
                "required": required == "Y", "description": description.replace(r"\|", "|")}
        plain = description.replace("`", "")
        default = re.search(r"(?:默认(?:值)?|缺省)\s*(?:为|[:：=])?\s*([+-]?\d+(?:\.\d+)?|true|false)(?![\w.])", plain, re.I)
        if default and item["type"] != "string":
            item["default"] = default[1].lower()
        if kind in {"integer", "number"}:
            span = re.search(r"(?:范围|取值)[^0-9]{0,8}(\d+)\s*(?:[-–—~～至到]|\.\.)\s*(\d+)", plain)
            maximum = re.search(r"(?:最大|不超过|上限)\s*(\d+)", plain)
            if span:
                item["minimum"], item["maximum"] = int(span[1]), int(span[2])
            elif maximum and "时间戳" not in plain and "自然月" not in plain and "自然日" not in plain:
                item["maximum"] = int(maximum[1])
            if name in {"page", "page_size"} and "minimum" not in item:
                item["minimum"] = 1
        # Date-shaped values use the exact format described for this field. Avoid
        # interpreting arbitrary strings that only mention another date field.
        if re.search(r"YYYY-?MM-?DD", plain) and "HH" not in plain and not re.search(r"时间戳|YYYYMMDDHH|YYYY-MM-DDT", plain):
            formats = list(dict.fromkeys(re.findall(r"YYYY-?MM-?DD", plain)))
            if len(formats) == 1:
                item["format"] = formats[0]
        if item["type"] == "boolean":
            item["enum"] = ["true", "false"]
        params.append(item)
    return params


def examples(text, path, params):
    required = {p["name"] for p in params if p["required"]}
    names = {p["name"] for p in params}
    choices = []
    example_section = text.split("## 接口示例", 1)[-1].split("## 数据样例", 1)[0]
    for line in re.sub(r"\\\n\s*", " ", example_section).splitlines():
        if not line.lstrip().startswith("curl "):
            continue
        words = shlex.split(line)
        url = next((word for word in words if word.startswith("https://market.ft.tech/gateway/api/")), "")
        parsed = urlsplit(url)
        if parsed.path != "/gateway" + path:
            continue
        values = dict(parse_qsl(parsed.query))
        for pos, word in enumerate(words[:-1]):
            if word in ("--data-urlencode", "--data", "-d"):
                name, sep, value = words[pos + 1].partition("=")
                if sep:
                    values[name] = value
        if values.keys() <= names:
            choices.append(values)
    defaults = {p["name"]: p["default"] for p in params if "default" in p}
    complete = next((example for example in choices if example.keys() >= required), None)
    if complete == {} and not defaults:
        complete = next((example for example in choices if example and example.keys() >= required), complete)
    if complete is None and not required:
        complete = {}
    if complete is None:
        return None
    return {**defaults, **complete}


def operation(tier, title, page):
    text, slug = page["content"], page["slug"]
    block = re.search(r"^## 输入参数\s*\n(.*?)(?=^## (?!#)|\Z)", text, re.M | re.S)[1]
    method = field(text, "方法")
    identifier = field(text, "接口").split(" / ")[0].strip("`")
    if method != "GET":
        raise ValueError(f"Unsupported method {method}: {slug}")
    paths = PATH.findall(field(text, "路径"))
    parts = [(path, parameters(block)) for path in paths]
    if slug == STOCK_LIST:
        full, realtime = block.split("stock-list 实时族", 1)
        parts = [(f"/api/v1/market/data/daec/stocks/{board}", parameters(full)) for board in ("all", "xshg", "xshe", "bjse")]
        parts += [(f"/api/v1/market/data/stock-list/{board}", parameters(realtime)) for board in ("chi-next", "star", "new")]
    if not parts:
        raise ValueError(f"No documented route: {slug}")
    # The official table calls this one item even though its doc covers several
    # fixed paths. Keep all documented paths as explicitly selectable variants.
    variants = []
    for path, params in parts:
        rules = []
        def rule(kind, *fields):
            if set(fields) <= {p["name"] for p in params}:
                rules.append({"kind": kind, "fields": list(fields)})
        if slug == "6je0p1c6":
            for p in params:
                if p["name"] in {"symbol", "symbols"}:
                    p["required"] = False
        if identifier in INPUT_CHOICES:
            kind, fields = INPUT_CHOICES[identifier]
            rule(kind, *fields)
        if re.search(r"`since_ts_millis`\s*(?:和|与)\s*`limit`\s*至少", text):
            rule("at_least_one", "since_ts_millis", "limit")
        if identifier in DATE_PAIRS:
            rule("together", "start_date", "end_date")
        if identifier in {"hsi_daily_weight", "ft_limit", "fut_settle", "index_fut_depth",
                          "szse_convertible_bond_matching_trades", "szse_convertible_bond_negotiated_trades",
                          "szse_convertible_bond_directed_trades"}:
            rule("exclusive", "trade_date", "start_date")
            rule("exclusive", "trade_date", "end_date")
        if identifier == "ft_limit":
            rule("at_least_one", "trade_date", "start_date")
        if identifier == "stock_unlock":
            rule("exclusive", "stock_code", "start_date")
        if identifier in {"etf_net_value", "get_fund_net_value", "get_fund_portfolio",
                          "get_fund_asset_allocation", "get_fund_net_value_performance"}:
            for name in ("nav_date", "report_date", "stat_date"):
                rule("exclusive", name, "start_date")
                rule("exclusive", name, "end_date")
        if identifier in {"balance", "cashflow", "income", "performance_forecasts_paginated"}:
            rule("unless", "stock_code", "year", "report_type", "page")
        if identifier in {"stock_announcements", "etf_announcements", "stock_prospectuses"}:
            rule("at_least_one", "etf_code" if identifier == "etf_announcements" else "stock_code", "start_date")
            rule("same", "start_date", "end_date")
        if identifier == "stk_limit":
            rule("together", "symbol_id", "market_id")
            rule("together", "start_date", "end_date")
            rule("exclusive", "trade_date", "start_date")
        for param in params:
            name = param["name"]
            options = CHOICES.get((identifier, name))
            if name == "adjust_kind" and all(v in param["description"] for v in ("none", "forward", "backward")):
                options = ("none", "forward", "backward")
            if options:
                param["enum"] = list(options)
                for choice in options:
                    if re.search(rf"默认(?:为)?\s*`?{re.escape(choice)}\b|`{re.escape(choice)}`（[^）]*默认", param["description"]):
                        param["default"] = choice
                        break
        presets = examples(text, path, params)
        if presets is None and len(parts) > 1 and variants:
            previous = {p["name"] for p in variants[0]["parameters"]}
            if previous == {p["name"] for p in params} and variants[0]["preset"] is not None:
                presets = variants[0]["preset"]
        if presets is None:
            raise ValueError(f"No complete HTTP example in the document: {slug} {path}")
        variant = {"path": path, "parameters": params, "preset": presets, "rules": rules}
        if identifier == "get_etf_pre":
            variant["preset_today"] = "date"
        variants.append(variant)
    breadcrumb = page["breadcrumb"]
    subgroup = " / ".join(section["title"] for section in breadcrumb[1:-1])
    return {
        "id": identifier, "method": method,
        "summary": title, "group": breadcrumb[0]["title"],
        **({"subgroup": subgroup} if subgroup else {}),
        "tier": tier, "docs_url": f"{DOC}/p/{slug}", "variants": variants,
    }


def catalog(index, fetch):
    operations = [operation(tier, title, fetch(slug)) for tier, title, slug in package_rows(index["content"])]
    identifiers = [op["id"] for op in operations]
    if len(set(identifiers)) != 225 or any(not re.fullmatch(r"[a-zA-Z0-9_]+", name) for name in identifiers):
        raise ValueError("Unexpected FTShare operation identifiers")
    return {"source": f"{DOC}/p/{INDEX}", "version": index["updated_at"], "operations": operations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, help="Read operation JSON from local public doc snapshots.")
    parser.add_argument("--index", type=Path, help="Read the plan overview JSON from a local snapshot.")
    args = parser.parse_args()
    with httpx.Client(timeout=25) as client:
        def fetch(slug):
            if args.pages and slug != INDEX:
                return json.loads((args.pages / f"{slug}.json").read_text())
            response = client.get(f"{DOC}/api/pages/{slug}")
            response.raise_for_status()
            return response.json()["data"]
        index = json.loads(args.index.read_text())["data"] if args.index else fetch(INDEX)
        if args.pages:
            result = catalog(index, fetch)
        else:
            slugs = [row[2] for row in package_rows(index["content"])]
            with ThreadPoolExecutor(max_workers=8) as pool:
                pages = dict(zip(slugs, pool.map(fetch, slugs), strict=True))
            result = catalog(index, pages.__getitem__)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
