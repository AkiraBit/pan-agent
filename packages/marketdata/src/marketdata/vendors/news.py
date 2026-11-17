"""东方财富个股新闻与公告的采集适配器。"""

from __future__ import annotations

import json as json_module
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from marketdata.http import market_get
from marketdata.symbol import Symbol
from marketdata.types import NewsArticle
from marketdata.vendors.base import NewsVendor as _NewsVendorBase

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str:
    return _HTML_TAG_RE.sub("", text or "").strip()


def _parse_epoch_millis(ms) -> datetime:
    """毫秒时间戳(雪球 created_at)→ UTC datetime;解析失败回退 EPOCH。"""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return _EPOCH


def _parse_datetime_str(s, fmt: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """"%Y-%m-%d %H:%M:%S" 中国来源的当地时间字符串 → UTC datetime;解析失败依次回退到纯日期、
    再回退 EPOCH(照搬 news_collector.py 两级 try/except 的容错顺序)。"""
    text = str(s or "").strip()
    if not text:
        return _EPOCH
    try:
        return datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return _EPOCH


# ---------------------------------------------------------------------------
# eastmoney_news(东财个股新闻搜索,search-api-web JSONP)
# ---------------------------------------------------------------------------

_EM_NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
_EM_NEWS_HOST = "search-api-web.eastmoney.com"
_EM_NEWS_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://so.eastmoney.com/",
    "Accept": "*/*",
}


def _eastmoney_news_importance(title: str) -> int:
    if any(k in title for k in ("重磅", "突发", "紧急", "重大", "独家")):
        return 2
    if any(k in title for k in ("快讯", "消息", "公告", "研报")):
        return 1
    return 0


def _build_search_params(keyword: str) -> dict:
    search_param = {
        "uid": "",
        "keyword": keyword,  # 用名称搜索效果远好于代码(照搬原逻辑)
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": 15,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    return {"cb": "jQuery", "param": json_module.dumps(search_param, separators=(",", ":"))}


def _parse_jsonp(text: str) -> dict | None:
    """剥 JSONP 外壳:"jQuery({...})" -> {...}。非预期结构返回 None(不 raise)。"""
    stripped = (text or "").strip()
    if not (stripped.startswith("jQuery(") and stripped.endswith(")")):
        return None
    try:
        data = json_module.loads(stripped[len("jQuery("):-1])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


class EastmoneyStockNewsVendor(_NewsVendorBase):
    name = "eastmoney_news"
    supports_markets = {"CN"}

    def fetch(self, symbols: list[Symbol], config: dict) -> list[NewsArticle]:
        if not symbols:
            return []
        names = (config or {}).get("symbol_names") or {}

        seen: set[str] = set()
        result: list[NewsArticle] = []
        for sym in symbols:
            code = sym.code
            keyword = names.get(code) or code  # 缺名 fallback 用代码搜索(照老逻辑)
            for article in self._search(keyword, code):
                if article.external_id in seen:
                    continue  # 同一新闻可能出现在多只股票搜索结果里,去重(照老逻辑)
                seen.add(article.external_id)
                result.append(article)
        return result

    @classmethod
    def fetch_by_keyword(cls, keyword: str) -> list[NewsArticle]:
        """按任意关键词(行业/主题词,如"新能源汽车")搜中文新闻,不需 symbol_names 映射。
        供 client.news_by_keyword 复用(照搬原 EastMoneyStockNewsCollector.fetch_by_keyword)。"""
        return cls()._search(keyword, keyword)

    def _search(self, keyword: str, symbol_tag: str) -> list[NewsArticle]:
        if not keyword:
            return []

        text = market_get(
            _EM_NEWS_URL,
            host_key=_EM_NEWS_HOST,
            params=_build_search_params(keyword),
            headers=_EM_NEWS_HEADERS,
            min_interval_s=0.2,
            timeout=8,
            retries=1,
            parse="text",
            verify=False,  # 对齐原 EastMoneyStockNewsCollector(verify_ssl=False)
            symbol=symbol_tag,
            log_label="东财个股新闻",
        )
        if text is None:
            return []

        data = _parse_jsonp(text)
        if not data or data.get("code") != 0:
            return []

        items = ((data.get("result") or {}).get("cmsArticleWebOld")) or []
        out: list[NewsArticle] = []
        for item in items:
            try:
                article = _parse_eastmoney_news_item(item, symbol_tag)
                if article:
                    out.append(article)
            except Exception:
                continue
        return out


def _parse_eastmoney_news_item(item: dict, symbol: str) -> NewsArticle | None:
    external_id = str(item.get("code", ""))
    if not external_id:
        return None

    title = item.get("title", "")
    if not title:
        return None
    title = _strip_html(title)
    content = _strip_html(item.get("content", ""))

    url = item.get("url", "") or f"https://finance.eastmoney.com/a/{external_id}.html"
    publish_time = _parse_datetime_str(item.get("date", ""))

    return NewsArticle(
        source="eastmoney_news",
        external_id=external_id,
        title=title,
        content=content,
        publish_time=publish_time,
        symbols=[symbol] if symbol else [],
        importance=_eastmoney_news_importance(title),
        url=url,
    )


# ---------------------------------------------------------------------------
# eastmoney(东财公告,ann API)
# ---------------------------------------------------------------------------

_EM_ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
_EM_ANN_HOST = "np-anotice-stock.eastmoney.com"


def _ann_importance(title: str, column_names: list[str]) -> int:
    if any(k in title for k in ("重大", "业绩预告", "业绩快报", "年报", "半年报")):
        return 3
    if any(k in title for k in ("季报", "分红", "增持", "减持")):
        return 2
    if any("临时" in c for c in column_names):
        return 1
    return 0


class EastmoneyAnnNewsVendor(_NewsVendorBase):
    name = "eastmoney"
    supports_markets = {"CN"}

    def fetch(self, symbols: list[Symbol], config: dict) -> list[NewsArticle]:
        a_share = sorted({s.code for s in symbols if len(s.code) == 6 and s.code.isdigit()})
        if not a_share:
            return []

        params = {
            "sr": -1,
            "page_size": int((config or {}).get("page_size") or 50),
            "page_index": 1,
            "ann_type": "A",
            "stock_list": ",".join(a_share),
            "f_node": 0,
            "s_node": 0,
        }
        headers = {"User-Agent": _UA}

        data = market_get(
            _EM_ANN_URL,
            host_key=_EM_ANN_HOST,
            params=params,
            headers=headers,
            min_interval_s=0.2,
            timeout=10,
            retries=1,
            parse="json",
            verify=False,  # 对齐原 EastMoneyNewsCollector(verify_ssl=False,东财 ann 端点 SSL 关闭)
            log_label="东财公告",
        )
        if not data or not data.get("success"):
            return []

        items = ((data.get("data") or {}).get("list")) or []
        result: list[NewsArticle] = []
        for item in items:
            try:
                codes = item.get("codes", []) or []
                stock_codes = [c.get("stock_code", "") for c in codes if c.get("stock_code")]
                if not stock_codes:
                    stock_codes = a_share[:1]
                article = _parse_ann_item(item, stock_codes)
                if article:
                    result.append(article)
            except Exception:
                continue
        return result


def _parse_ann_item(item: dict, symbols: list[str]) -> NewsArticle | None:
    external_id = str(item.get("art_code", ""))
    if not external_id:
        return None

    title = item.get("title", "")
    if not title:
        return None

    publish_time = _parse_datetime_str(item.get("notice_date", ""))

    columns = item.get("columns", []) or []
    column_names = [str(c.get("column_name") or "") for c in columns]
    importance = _ann_importance(title, column_names)

    symbol_for_url = symbols[0] if symbols else ""
    url = f"https://data.eastmoney.com/notices/detail/{symbol_for_url}/{external_id}.html"

    return NewsArticle(
        source="eastmoney",
        external_id=external_id,
        title=title,
        content="",  # 公告通常只有标题,内容需另外获取(照搬原逻辑)
        publish_time=publish_time,
        symbols=symbols,
        importance=importance,
        url=url,
    )
