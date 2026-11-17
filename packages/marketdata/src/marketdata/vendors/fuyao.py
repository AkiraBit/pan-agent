"""Fuyao's A-share REST API. The host supplies the current API key."""

from datetime import datetime, timedelta, timezone
import math
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from marketdata.errors import VendorError
from marketdata.http import within_budget
from marketdata.types import Bar, DividendItem, DragonTigerItem, FlashNews, Fundamentals, NewsArticle, Quote

ORIGIN = "https://fuyao.aicubes.cn"
SHANGHAI = ZoneInfo("Asia/Shanghai")
PRICE_FIELDS = {
    "open_price": "open_price", "high_price": "high_price", "low_price": "low_price",
    "prev_close": "prev_price", "change_amount": "price_change", "change_pct": "price_change_ratio_pct",
    "volume": "volume", "turnover": "turnover",
}


def _stock_code(symbol):
    code = symbol.code.upper()
    if re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code):
        return code
    if re.fullmatch(r"[0-9]{6}", code):
        return f"{code}.{symbol.to_tencent()[:2].upper()}"
    return None


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _as_url(value):
    return value if isinstance(value, str) and urlsplit(value).scheme in {"http", "https"} else ""


def _time(value):
    seconds = _number(value)
    if seconds is not None and seconds > 0:
        try:
            return datetime.fromtimestamp(seconds / 1000, SHANGHAI)
        except (OSError, OverflowError, ValueError):
            pass
    return None


def _data(client, path, params):
    try:
        response = client.get(f"{ORIGIN}/api/a-share/prices/{path}", params=params, timeout=within_budget(8))
        if response.status_code in (401, 403):
            raise VendorError("同花顺 API Key 无效或无访问权限。")
        if response.status_code == 429:
            raise VendorError("同花顺 API 调用频率受限，请稍后重试。")
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise VendorError("无法连接同花顺行情 API，请稍后重试。") from None
    code = payload.get("code") if isinstance(payload, dict) else None
    if code == 2001:
        raise VendorError("同花顺 API Key 无效，请在设置中检查。")
    if code == 2003:
        raise VendorError("此同花顺 API Key 没有该接口的访问权限。")
    if code == 4001:
        raise VendorError("同花顺 API 调用频率受限，请稍后重试。")
    if type(code) is not int or code != 0:
        raise VendorError(f"同花顺行情 API 返回错误（{code}）。" if type(code) is int
                          else "同花顺行情 API 响应格式无效。")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        raise VendorError("同花顺行情 API 响应格式无效。")
    return data


class FuyaoVendor:
    name = "fuyao"
    supports_markets = {"CN"}

    def __init__(self, api_key=None):
        self.api_key = api_key

    def client(self):
        if self.api_key is None:
            raise VendorError("请先配置同花顺 API Key。")
        return httpx.Client(headers={"X-api-key": self.api_key()}, timeout=8, follow_redirects=False)


class FuyaoQuoteVendor(FuyaoVendor):
    def fetch(self, symbols, config):
        requested = {code: symbol for symbol in symbols if (code := _stock_code(symbol))}
        if not requested:
            return []
        codes = list(requested)
        quotes = {}
        with self.client() as client:
            for start in range(0, len(codes), 100):
                batch = codes[start:start + 100]
                data = _data(client, "snapshot", {"thscodes": ",".join(batch)})
                at = _time(data.get("timestamp"))
                for row in data["item"]:
                    if not isinstance(row, dict) or row.get("thscode") not in batch:
                        continue
                    code = row["thscode"]
                    price = _number(row.get("last_price"))
                    if price is not None and price > 0:
                        quotes[code] = Quote(
                            symbol=requested[code].code, market="CN", current_price=price,
                            source=self.name, timestamp=datetime.now(timezone.utc),
                            quote_date=at.date() if at else None,
                            # A batch timestamp is the latest across the batch, not a per-stock time.
                            source_timestamp=at if len(batch) == 1 else None,
                            **{target: _number(row.get(field)) for target, field in PRICE_FIELDS.items()},
                        )
        return [quotes[code] for code in codes if code in quotes]


class FuyaoKlineVendor(FuyaoVendor):
    def fetch(self, symbols, config):
        code = _stock_code(symbols[0]) if symbols else None
        if code is None:
            return []
        days = max(1, int(config.get("days", 120)))
        end = datetime.now(SHANGHAI)
        # PanWatch requests a number of trading bars; the upstream takes a calendar range.
        start = end - timedelta(days=min(days * 2 + 10, 3650))
        with self.client() as client:
            data = _data(client, "historical", {
                "thscode": code, "interval": "1d", "adjust": "forward",
                "start": int(start.timestamp() * 1000), "end": int(end.timestamp() * 1000),
            })
        bars = {}
        for row in data["item"]:
            if not isinstance(row, dict):
                continue
            at = _time(row.get("date_ms"))
            prices = {field: _number(row.get(f"{field}_price")) for field in ("open", "high", "low", "close")}
            if at is not None and all(value is not None and value > 0 for value in prices.values()):
                day = at.date().isoformat()
                bars[day] = Bar(date=day, **prices, volume=_number(row.get("volume")) or 0,
                                turnover=_number(row.get("turnover")), source=self.name)
        return [bars[day] for day in sorted(bars)[-days:]]


class FuyaoBusinessVendor:
    name = "fuyao"
    supports_markets = {"CN"}

    def __init__(self, read=None):
        self.read = read

    def call(self, operation, **params):
        if self.read is None:
            raise VendorError("同花顺业务数据源未配置。")
        return self.read(operation, params) or {}


class FuyaoFundamentalsVendor(FuyaoBusinessVendor):
    def fetch(self, symbols, config):
        requested = {code: sym for sym in symbols if (code := _stock_code(sym))}
        result = []
        codes = list(requested)
        for start in range(0, len(codes), 10):
            batch = codes[start:start + 10]
            thscodes = ",".join(batch)
            by_code = {}
            try:
                valuations = self.call("get_a_share_valuations_snapshot", thscodes=thscodes)
                by_code = {row.get("thscode"): row for row in valuations.get("item", [])}
            except RuntimeError:
                pass  # Valuation and reports can be enabled independently.
            reports = {}
            try:
                income = self.call("get_a_share_financials_income_statements_batch",
                                   thscodes=thscodes, period="annual", limit=2)
                reports = {row.get("thscode"): row.get("item") or [] for row in income.get("item", [])}
            except RuntimeError:  # A key can have valuation access without report access.
                pass
            for code in batch:
                valuation = by_code.get(code, {})
                rows = sorted(reports.get(code, []), key=lambda row: row.get("period_end_ms") or 0, reverse=True)
                if not valuation and not rows:
                    continue
                current, previous = (rows + [{}, {}])[:2]
                revenue, profit = (_number(current.get(field)) for field in ("operating_income", "parent_holder_net_profit"))
                at = _time(current.get("period_end_ms"))

                def yoy(value, field):
                    prior = _number(previous.get(field))
                    latest_year, prior_year = current.get("fiscal_year"), previous.get("fiscal_year")
                    if type(latest_year) is int and latest_year - 1 == prior_year and value is not None and prior:
                        return (value - prior) / abs(prior) * 100
                    return None

                result.append(Fundamentals(
                    symbol=requested[code].code, market="CN", name=valuation.get("name") or "",
                    pe_ttm=_number(valuation.get("pe_ttm")), pb=_number(valuation.get("pb_mrq")),
                    ps_ttm=_number(valuation.get("ps_ttm")), eps=_number(current.get("basic_eps")),
                    revenue=revenue, net_profit=profit, report_date=at.date().isoformat() if at else "",
                    revenue_yoy=yoy(revenue, "operating_income"), net_profit_yoy=yoy(profit, "parent_holder_net_profit"),
                    source=self.name, currency="CNY",
                ))
        return result


class FuyaoDragonTigerVendor(FuyaoBusinessVendor):
    def fetch(self, symbols, config):
        data = self.call("get_a_share_special_data_dragon_tiger_list", board_type="all", date=config.get("date"))
        day = data.get("trade_date")
        if not day or config.get("date") and day != config["date"]:
            return []
        result = []
        # One stock can be reported for several window lengths. Preserve the
        # provider's highest-ranked record on the daily leaderboard.
        seen = set()
        for row in data.get("stock_items") or []:
            code, change = row.get("ticker"), _number(row.get("change"))
            if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code) or code in seen:
                continue
            seen.add(code)
            result.append(DragonTigerItem(
                trade_date=day, symbol=code, name=row.get("name") or "",
                reason=row.get("limit_reason"), change_pct=change * 100 if change is not None else None,
                net_buy=_number(row.get("net_value")), buy_amt=_number(row.get("buy_value")),
                sell_amt=_number(row.get("sell_value")),
            ))
        return result


class FuyaoDividendVendor(FuyaoBusinessVendor):
    def fetch(self, symbols, config):
        result = []
        for symbol in symbols:
            if not (code := _stock_code(symbol)):
                continue
            data = self.call("get_a_share_corporate_actions_adjustment_factors", thscode=code)
            if data.get("thscode") != code:
                continue
            for row in data.get("item") or []:
                at, cash = _time(row.get("ex_date_ms")), _number(row.get("dividend_per_share"))
                if at and cash is not None and cash > 0:
                    result.append(DividendItem(ex_date=at.date().isoformat(), symbol=symbol.code,
                                               dividend_per_share=cash, source=self.name))
        return result


class FuyaoNewsVendor(FuyaoBusinessVendor):
    def fetch(self, symbols, config):
        found = {}
        for symbol in symbols[:12]:
            if not (code := _stock_code(symbol)):
                continue
            data = self.call("get_news_stock_timeline_list", thscode=code, offset="first", size=20)
            for row in data.get("items") or []:
                stamp, identity, title = _time(row.get("publish_time_ms")), row.get("id"), row.get("title")
                if stamp and identity and isinstance(title, str) and title:
                    key = str(identity)
                    if key not in found:
                        found[key] = NewsArticle(
                            source=self.name, external_id="fuyao:" + key, title=title,
                            content=row.get("summary") or "", publish_time=stamp,
                            symbols=[], url=_as_url(row.get("jump_url")),
                        )
                    if symbol.code not in found[key].symbols:
                        found[key].symbols.append(symbol.code)
        return list(found.values())


class FuyaoFlashNewsVendor(FuyaoBusinessVendor):
    def fetch(self, symbols, config):
        data = self.call("get_news_flash_list", tag_id=21103, seq="0")
        result = []
        for row in data.get("items") or []:
            stamp, identity, title = _time(row.get("create_time_ms")), row.get("id"), row.get("title")
            if stamp and identity and isinstance(title, str) and title:
                result.append(FlashNews(source=self.name, external_id="fuyao:" + str(identity),
                                        title=title, content=row.get("summary") or "", publish_time=stamp,
                                        url=_as_url(row.get("encoded_url"))))
        return result
