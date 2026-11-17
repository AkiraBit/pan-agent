"""Routing identity is independent of the provider's REST catalog category."""
from . import ftshare_rest, fuyao_business, fuyao_rest, tushare_rest

# The values here are consumed by working runtime adapters, never inferred from a title.
FTSHARE_ROUTES = {
    "stock_daec_stocks": "quote",
    "stock_candlesticks": "kline",
    "index_candlesticks": "index_kline",
    "trading_calendar": "trading_calendar",
}
PAIRED_CAPABILITIES = frozenset(FTSHARE_ROUTES.values())
FALLBACK_PROVIDERS = ("ftshare", "fuyao")
# Scope of a verified *shared* contract. The FTShare calendar also supports HK independently.
FALLBACK_MARKET = "CN"
CATEGORIES = {
    "quote": "quote_kline", "kline": "quote_kline", "index_quote": "quote_kline",
    "index_kline": "quote_kline", "index_constituents": "quote_kline",
    "trading_calendar": "quote_kline", "stock_search": "quote_kline",
    "etf_turnover": "etf", "etf_nav": "etf", "etf_adjusted_history": "etf",
    "news": "news", "events": "news", "flash_news": "news",
    "fundamentals": "fundamentals", "dividend": "fundamentals", "shareholders": "fundamentals",
    "market_sentiment": "capital", "auction": "capital", "dragon_tiger": "capital",
    "capital_flow": "capital", "northbound": "capital", "margin": "capital", "ipo": "capital",
    "fund_holdings": "research", "fund_research": "research", "fund_backtest": "research",
    "futures_research": "research", "options_research": "research", "chart": "chart",
}


def types_for(kind: str, *, operation: str | None = None) -> tuple[str, ...]:
    fuyao_ops = (operation,) if operation else fuyao_business.NATIVE_OPERATIONS.get(kind, ())
    return (kind, *(ftshare_rest.TYPE_PREFIX + op for op, route in FTSHARE_ROUTES.items() if route == kind),
            *(fuyao_rest.TYPE_PREFIX + op for op in fuyao_ops))


def uses_fallback(kind: str, market: str | None) -> bool:
    return kind in PAIRED_CAPABILITIES and market == FALLBACK_MARKET


def candidates(kind, market, available, *, independent=()):
    """Resolve before calling: only the paired contract can try a second provider.

    For independent contracts, callers can nominate an established business
    provider. The choice is made from enabled, compatible sources, not their
    stored numeric priorities or the outcome of a previous request.
    """
    providers = tuple(dict.fromkeys(available))
    if uses_fallback(kind, market):
        return [provider for provider in FALLBACK_PROVIDERS if provider in providers]
    if kind == "news":
        return list(providers)
    return [provider for provider in dict.fromkeys((*independent, *providers)) if provider in providers][:1]


def metadata(source, labels):
    kind = source.type
    op = ftshare_rest.operation_for(kind) if source.provider == "ftshare" else None
    fuyao = fuyao_rest.operation_for(kind) if source.provider == "fuyao" else None
    capability = FTSHARE_ROUTES.get(op["id"]) if op else None
    if fuyao:
        business = fuyao_business.BY_OPERATION[fuyao["id"]]
        if fuyao["id"] in fuyao_business.NATIVE_OPERATIONS.get(business, ()):
            capability = business
    if capability in PAIRED_CAPABILITIES:
        return dict(key=capability, mode="fallback", label=labels.get(capability, capability),
                    category=CATEGORIES[capability], markets=[FALLBACK_MARKET])
    if kind == "news" or capability == "news":
        return dict(key="news", mode="aggregate", label=labels.get("news", "news"), category="news")
    if fuyao:
        return dict(key=business, mode="direct", label=labels.get(business, business),
                    category=CATEGORIES.get(business, "other"))
    if op:
        label = " · ".join(filter(None, (op["group"], op.get("subgroup"))))
        return dict(key="rest:" + label, mode="direct", label=label, category="ftshare_rest")
    tushare = tushare_rest.operation_for(kind) if source.provider == "tushare" else None
    if tushare:
        label = " · ".join(filter(None, (tushare["group"], tushare.get("subgroup"))))
        return dict(key="rest:tushare:" + label, mode="direct", label=label, category="tushare_rest")
    return dict(key=kind, mode="direct", label=labels.get(kind, kind), category=CATEGORIES.get(kind, "other"))
