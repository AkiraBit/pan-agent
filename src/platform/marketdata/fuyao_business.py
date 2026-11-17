"""Map the reviewed REST operations to configurable PanWatch capabilities."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.platform.marketdata.source_activation import paused_providers, provider_group
from src.platform.persistence.models import DataSource
from . import fuyao_credentials, fuyao_rest, source_calls


def capability(operation: dict) -> str:
    domain, family, action = operation["path"].split("/")[2:5]
    if domain == "a-share":
        if family == "prices":
            return "quote" if action == "snapshot" else "kline"
        if family in {"financials", "valuations"}:
            return "fundamentals"
        if family == "corporate-actions":
            return "dividend"
        if family == "calendar":
            return "trading_calendar"
        if family == "ipo":
            return "ipo"
        if family == "auction" or action.startswith("auction-"):
            return "auction"
        if action.startswith("dragon-tiger-"):
            return "dragon_tiger"
        return "market_sentiment"
    if domain == "a-share-index":
        if family == "prices":
            return "index_quote" if action == "snapshot" else "index_kline"
        return "index_constituents"
    if domain == "fund":
        if family == "market":
            return "etf_turnover" if action == "snapshot" else "etf_adjusted_history"
        if family == "performance" and action == "nav":
            return "etf_nav"
        if family == "portfolio":
            return "fund_holdings"
        return "fund_backtest" if family == "backtest" else "fund_research"
    if domain == "news":
        return "flash_news" if family == "flash" else "news"
    return {"meta": "stock_search", "futures": "futures_research", "options": "options_research", "hk-share": "ipo"}[domain]


BY_OPERATION = {op_id: capability(op) for op_id, op in fuyao_rest.OPERATIONS.items()}
BY_CAPABILITY: dict[str, list[str]] = defaultdict(list)
for _op_id, _kind in BY_OPERATION.items():
    BY_CAPABILITY[_kind].append(_op_id)

# Business categories are used for display and for migrating old settings, never as switches.
NAMES = {
    "quote": "同花顺 A 股行情", "kline": "同花顺 A 股日 K 线", "fundamentals": "同花顺 A 股财报与估值",
    "dividend": "同花顺 A 股分红与复权", "dragon_tiger": "同花顺 A 股龙虎榜",
    "news": "同花顺资讯与公告", "flash_news": "同花顺快讯",
    "trading_calendar": "同花顺 A 股交易日历", "stock_search": "同花顺标的检索",
    "index_quote": "同花顺指数行情", "index_kline": "同花顺指数日 K 线",
    "index_constituents": "同花顺指数与板块成分", "market_sentiment": "同花顺热榜与股票池",
    "auction": "同花顺集合竞价", "ipo": "同花顺 A 股与港股新股",
    "etf_turnover": "同花顺 ETF 成交额", "etf_adjusted_history": "同花顺 ETF 前复权日线", "etf_nav": "同花顺基金净值",
    "fund_holdings": "同花顺基金持仓与配置", "fund_research": "同花顺基金与基金经理研究",
    "fund_backtest": "同花顺基金回测", "futures_research": "同花顺期货研究", "options_research": "同花顺期权研究",
}
ETF = {"etf_turnover", "etf_adjusted_history", "etf_nav"}
WORKSPACE_CAPABILITIES = {"index_constituents", "ipo", "etf_adjusted_history", "fund_holdings",
                          "fund_research", "fund_backtest", "futures_research", "options_research"}
NATIVE = {"quote", "kline", "fundamentals", "dividend", "dragon_tiger", "news", "flash_news",
          "trading_calendar", "stock_search", "index_quote", "index_kline", "auction", "market_sentiment",
          "etf_turnover", "etf_nav", *WORKSPACE_CAPABILITIES}
DEFAULT_COMPETITORS = {
    "stock_search": ("eastmoney", "东方财富标的检索"),
    "index_quote": ("tencent", "腾讯指数行情"),
    "index_kline": ("eastmoney", "东方财富指数日 K 线"),
    "market_sentiment": ("eastmoney", "东方财富涨跌停股票池"),
}
EXTRA_COMPETITORS = {"index_kline": ("tencent", "腾讯指数日 K 线")}

NATIVE_OPERATIONS = {
    "quote": ("get_a_share_prices_snapshot",),
    "kline": ("get_a_share_prices_historical",),
    "fundamentals": ("get_a_share_valuations_snapshot", "get_a_share_financials_income_statements_batch"),
    "dividend": ("get_a_share_corporate_actions_adjustment_factors",),
    "dragon_tiger": ("get_a_share_special_data_dragon_tiger_list",),
    "news": ("get_news_stock_timeline_list",),
    "flash_news": ("get_news_flash_list",),
    "trading_calendar": ("get_a_share_calendar_trading_days",),
    "stock_search": ("get_meta_tickers_search",),
    "index_quote": ("get_a_share_index_prices_snapshot",),
    "index_kline": ("get_a_share_index_prices_historical",),
    "auction": ("get_a_share_auction_snapshot",),
    "etf_nav": ("get_fund_performance_nav",),
    "etf_turnover": ("get_fund_market_snapshot",),
}


def seeds():
    for op in fuyao_rest.OPERATIONS.values():
        yield dict(name=op["summary"], type=fuyao_rest.TYPE_PREFIX + op["id"], provider="fuyao", config={},
                   enabled=False, priority=1, supports_batch=False, test_symbols=[])
    for priority, competitors in [(0, DEFAULT_COMPETITORS), (2, EXTRA_COMPETITORS)]:
        for kind, (provider, name) in competitors.items():
            yield dict(name=name, type=kind, provider=provider, config={}, enabled=True, priority=priority,
                       supports_batch=kind == "index_quote", test_symbols=[])


class Unavailable(RuntimeError):
    pass


def active_operations(db: Session) -> set[str]:
    if not fuyao_credentials.configured(fuyao_credentials.read(db)):
        return set()
    return {kind.removeprefix(fuyao_rest.TYPE_PREFIX) for kind in source_calls.enabled_types(db, fuyao_credentials.PROVIDER)
            if fuyao_rest.operation_for(kind)}


async def fetch(operation_id: str, args: dict, *, bind=None):
    """Use the persisted source switch on every request, including assistant runs."""
    response = await source_calls.call(fuyao_credentials.PROVIDER, operation_id, params=args, bind=bind)
    if not 200 <= response["http_status"] < 300 or response["business_code"] != 0:
        code = response["business_code"]
        raise Unavailable(f"同花顺数据不可用（HTTP {response['http_status']}，业务码 {code}）。")
    return json.loads(response["response_json"]).get("data")


def marketdata_read(operation_id: str, args: dict):
    # Synchronous consumers run in the market-data worker thread.
    return asyncio.run(fetch(operation_id, args))


def providers(kind: str, *, market: str = "CN", available=None, operation: str | None = None) -> list[str]:
    """Select the policy's eligible providers for the caller's supported adapters."""
    from src.platform.persistence.database import SessionLocal
    from . import call_order, provider_credentials

    defaults = [items[kind][0] for items in (DEFAULT_COMPETITORS, EXTRA_COMPETITORS) if kind in items]
    if kind == "index_kline" and market != "CN":
        defaults.reverse()  # Tencent covers the overseas index codes used in the app.
    with SessionLocal() as db:
        rows = db.scalars(select(DataSource).where(DataSource.type.in_(call_order.types_for(kind, operation=operation)))
                          .order_by(DataSource.id)).all()
        paused = paused_providers(db)
        active = [row for row in rows if row.enabled and provider_group(row.provider) not in paused]
        configured = any(row.provider == "fuyao" for row in active) and (
            fuyao_credentials.configured(fuyao_credentials.read(db))
        )
        ftshare_configured = any(row.provider == "ftshare" for row in active) and (
            provider_credentials.configured(provider_credentials.read(db, "ftshare"))
        )
        result = [row.provider for row in active if row.provider in defaults
                  or row.provider == "fuyao" and configured or row.provider == "ftshare" and ftshare_configured]
        for default in defaults:
            if default not in paused and not any(row.provider == default for row in rows):
                result.append(default)
        if available is not None:
            result = [provider for provider in result if provider in available]
        return call_order.candidates(kind, market, result, independent=defaults)
