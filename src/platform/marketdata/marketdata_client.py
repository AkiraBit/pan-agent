"""PanWatch ↔ marketdata 接线:DB 配置端口 + 单例 + flag 门控的报价兼容层。

- DbConfigProvider:把 DataSource 表映射成 marketdata 的 SourceConfig(实现 ConfigProvider 端口)。
- get_market_data():进程级单例(无状态 vendor + 现查 DB 的配置端口)。
- md_quote_rows():新包 MarketData.quotes 转 dict,返回 list[dict](与旧 orchestrator 输出同形)。
- md_news()/md_news_by_keyword():新包 MarketData.news/news_by_keyword 转 host NewsItem。
"""

from __future__ import annotations

import logging

from marketdata import MarketData, Quote, SourceConfig
from marketdata.registry import VENDOR_CLASSES_BY_TYPE
from src.platform.marketdata.source_activation import active_source
from . import call_order, ftshare_market, fuyao_business, fuyao_credentials, provider_credentials

logger = logging.getLogger(__name__)

# Existing readers for markets and data that do not have a verified FTShare/Fuyao pair.
INDEPENDENT_PROVIDERS = {
    "quote": ("tencent", "sina"), "kline": ("tencent", "eastmoney"),
    "capital_flow": ("eastmoney", "sina"), "events": ("eastmoney",),
    "flash_news": ("cls", "sina", "eastmoney", "fuyao"),
    "fundamentals": ("tencent", "eastmoney", "fuyao"),
    "dragon_tiger": ("eastmoney", "fuyao"), "dividend": ("eastmoney", "fuyao"),
}


class DbConfigProvider:
    """Resolve the host's routing policy without using stored priorities."""

    def _query_rows(self, datatype: str) -> list:
        from src.platform.persistence.database import SessionLocal
        from src.platform.persistence.models import DataSource

        db = SessionLocal()
        try:
            rows = (
                db.query(DataSource)
                .filter(DataSource.type.in_(call_order.types_for(datatype)), active_source())
                .order_by(DataSource.id)
                .all()
            )
            if any(row.provider == fuyao_credentials.PROVIDER for row in rows) and (
                not fuyao_credentials.configured(fuyao_credentials.read(db))
            ):
                rows = [row for row in rows if row.provider != fuyao_credentials.PROVIDER]
            if any(row.provider == "ftshare" for row in rows) and not (
                provider_credentials.configured(provider_credentials.read(db, "ftshare"))
            ):
                rows = [row for row in rows if row.provider != "ftshare"]
            return rows
        finally:
            db.close()

    def sources_for(self, datatype: str, market: str | None) -> list[SourceConfig]:
        adapters = dict(VENDOR_CLASSES_BY_TYPE.get(datatype, {}))
        adapters.update(EXTRA_VENDORS.get(datatype, {}))
        eligible = {}
        fuyao_types = []
        for row in self._query_rows(datatype):
            adapter = adapters.get(row.provider)
            if adapter and (market is None or not adapter.supports_markets or market in adapter.supports_markets):
                eligible.setdefault(row.provider, row)
                if row.provider == "fuyao":
                    fuyao_types.append(row.type)
        vendors = call_order.candidates(datatype, market, eligible, independent=INDEPENDENT_PROVIDERS.get(datatype, ()))
        ranks = call_order.FALLBACK_PROVIDERS if call_order.uses_fallback(datatype, market) else ()
        return [SourceConfig(vendor=vendor, priority=ranks.index(vendor) if ranks else 0,
                             enabled=True, config={"enabled_operations": fuyao_types} if vendor == "fuyao"
                             else eligible[vendor].config or {},
                             supports_batch=bool(eligible[vendor].supports_batch)) for vendor in vendors]


_md: MarketData | None = None
EXTRA_VENDORS = {
    "quote": {"ftshare": ftshare_market.FtshareQuoteVendor()},
    "kline": {"ftshare": ftshare_market.FtshareKlineVendor()},
}


def get_market_data() -> MarketData:
    """进程级单例。vendor 无状态、配置现查 DB,故无需失效钩子。"""
    global _md
    if _md is None:
        _md = create_market_data(config=DbConfigProvider())
    return _md


def create_market_data(**kwargs):
    return MarketData(fuyao_api_key=fuyao_credentials.get_api_key,
                      fuyao_transport=fuyao_business.marketdata_read, extra_vendors=EXTRA_VENDORS, **kwargs)


def reset_market_data() -> None:
    """测试或热重载时重置单例。"""
    global _md
    _md = None


def _quote_to_row(q: Quote) -> dict:
    """marketdata.Quote → 旧 orchestrator 同形 dict。"""
    return {
        "symbol": q.symbol,
        "name": q.name,
        "market": q.market,
        "current_price": q.current_price,
        "change_pct": q.change_pct,
        "change_amount": q.change_amount,
        "prev_close": q.prev_close,
        "open_price": q.open_price,
        "high_price": q.high_price,
        "low_price": q.low_price,
        "volume": q.volume,
        "turnover": q.turnover,
        "turnover_rate": q.turnover_rate,
        "volume_ratio": q.volume_ratio,
        "pe_ratio": q.pe_ratio,
        "circulating_market_value": q.circulating_market_value,
        "total_market_value": q.total_market_value,
        "quote_date": q.quote_date.isoformat() if q.quote_date else None,
        "source_timestamp": q.source_timestamp.isoformat() if q.source_timestamp else None,
        "observed_at": q.timestamp.isoformat(),
        "source": q.source,
        "stale": q.stale,
    }


def md_quote_rows(symbols: list[str], market: str, *, max_age_seconds=None, stale_if_error_seconds=0, trade_date=None) -> list[dict]:
    """批量报价,返回 list[dict](与旧 orchestrator 输出同形)。

    同步函数;async 调用方用 `await asyncio.to_thread(md_quote_rows, ...)`。
    """
    syms = list(symbols)
    if not syms:
        return []
    options = {} if max_age_seconds is None and not stale_if_error_seconds and trade_date is None else {
        "max_age_seconds": max_age_seconds, "stale_if_error_seconds": stale_if_error_seconds, "trade_date": trade_date}
    quotes = get_market_data().quotes(syms, market=market, **options)
    return [_quote_to_row(q) for q in quotes]


def _article_to_newsitem(a):
    """marketdata.NewsArticle → host NewsItem(同名字段直拷)。

    lazy import 避免与 news_collector 的模块级循环引用(news_collector 会
    在模块级 import 本模块的 md_news)。
    """
    from src.platform.marketdata.collectors.news_collector import NewsItem

    return NewsItem(
        source=a.source,
        external_id=a.external_id,
        title=a.title,
        content=a.content,
        publish_time=a.publish_time,
        symbols=a.symbols,
        importance=a.importance,
        url=a.url,
    )


def md_news(
    symbols: list[str], since_hours: int = 2, names: dict[str, str] | None = None
) -> list:
    """聚合新闻(个股新闻 + 公告),返回 list[NewsItem](与旧 NewsCollector.fetch_all 同形)。

    host 侧可以用 datetime.now() 做 since 过滤(包内不允许偷偷调 datetime.now(),
    必须由调用方显式传 now)。

    同步函数;async 调用方用 `await asyncio.to_thread(md_news, ...)`。
    """
    from datetime import datetime, timezone

    # 包内 news vendor 的 publish_time 是 aware(UTC);这里的 now 也必须 aware,
    # 否则 since 过滤会 "can't compare offset-naive and offset-aware datetimes"。
    arts = get_market_data().news(
        list(symbols or []), since_hours=since_hours, names=names,
        now=datetime.now(timezone.utc),
    )
    return [_article_to_newsitem(a) for a in arts]


def md_news_by_keyword(keyword: str) -> list:
    """按关键词(行业/主题词)搜中文新闻,返回 list[NewsItem]。同步。"""
    arts = get_market_data().news_by_keyword(keyword)
    return [_article_to_newsitem(a) for a in arts]


def md_stock_data(symbols: list[str], market: str) -> list:
    """返回 list[StockData](旧 AkshareCollector.get_stock_data 同形)。同步。"""
    from src.platform.marketdata.models import MarketCode, StockData

    syms = list(symbols)
    if not syms:
        return []
    quotes = get_market_data().quotes(syms, market=market)
    return [StockData(
        symbol=q.symbol, name=q.name or "", market=MarketCode(q.market),
        current_price=q.current_price or 0.0, change_pct=q.change_pct or 0.0,
        change_amount=q.change_amount or 0.0, volume=q.volume or 0.0,
        turnover=q.turnover or 0.0, open_price=q.open_price or 0.0,
        high_price=q.high_price or 0.0, low_price=q.low_price or 0.0,
        prev_close=q.prev_close or 0.0, source=q.source) for q in quotes]
