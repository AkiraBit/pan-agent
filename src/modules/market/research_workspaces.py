"""Product views for market research and their source contracts.

View names describe business tasks and stay stable if a provider changes.
The registry is also the allowlist used by the browser-facing API.
"""

from dataclasses import dataclass

from src.platform.marketdata import fuyao_business, fuyao_rest


@dataclass(frozen=True)
class View:
    id: str
    title: str
    operation: str
    section: str
    chart: str | None = None


def views(prefix: str, section: str, *specs) -> list[View]:
    return [View(name, title, f"get_{prefix}{operation}", section, extras[0] if extras else None)
            for name, title, operation, *extras in specs]


WORKSPACES = {
    "index_constituents": [
        *views("a_share_index_", "directory",
               ("directory", "指数目录", "catalog_ths_index_list"),
               ("members", "指数成分股", "constituents_ths_stock_list"),
               ("membership", "个股所属板块", "constituents_ths_index_list_by_stock")),
    ],
    "ipo": [
        *views("a_share_ipo_", "mainland", ("mainland", "A 股发行与申购", "calendar_list")),
        *views("hk_share_ipo_", "hongKong",
               ("calendar", "港股认购日历", "calendar_list"),
               ("filings", "港股递表进度", "application_list"),
               ("issue", "港股发行详情", "issue_detail")),
    ],
    "etf_adjusted_history": [
        *views("fund_market_", "prices",
               ("history", "单只 ETF 走势", "historical", "close_price"),
               ("compare", "ETF 区间对比", "historical_batch", "close_price")),
    ],
    "fund_holdings": [
        *views("fund_portfolio_", "portfolio",
               ("holdings", "最新重仓", "holdings"),
               ("assets", "资产配置", "asset_allocation"),
               ("industries", "行业配置", "industry_allocation")),
        *views("fund_portfolio_", "disclosures",
               ("stock-reports", "股票披露期", "stock_report_dates"),
               ("stock-positions", "历史股票持仓", "stock_history"),
               ("bond-reports", "债券披露期", "bond_report_dates"),
               ("bond-positions", "历史债券持仓", "bond_history")),
    ],
    "fund_research": [
        *views("fund_", "profile",
               ("profile", "基金档案", "profile_detail"),
               ("diagnostics", "基金诊断", "diagnostics_detail"),
               ("dividends", "分红记录", "corporate_actions_dividends"),
               ("news", "基金资讯", "news_article_list")),
        *views("fund_performance_", "performance",
               ("returns", "区间收益", "returns"),
               ("metrics", "历史业绩指标", "indicators_historical"),
               ("drawdowns", "最大回撤", "drawdowns")),
        *views("fund_", "financials",
               ("financial-metrics", "财务指标", "financials_indicators"),
               ("income", "利润表", "financials_income_statements"),
               ("balance", "资产负债表", "financials_balance_sheets"),
               ("owners", "持有人结构", "holders_detail"),
               ("top-owners", "前十大持有人", "holders_top")),
        *views("fund_", "managers",
               ("company", "基金公司", "companies_detail"),
               ("manager", "基金经理档案", "managers_detail"),
               ("manager-style", "投资风格", "managers_investment_style"),
               ("manager-performance", "经理业绩", "managers_performance", "manager_return_pct"),
               ("manager-career", "从业经历", "managers_experience")),
        *views("fund_", "distribution",
               ("offerings", "基金募集", "offerings_list"),
               ("qdii-summary", "QDII 额度概览", "quota_summary"),
               ("qdii-funds", "QDII 基金与申购状态", "quota_list")),
    ],
    "fund_backtest": [
        *views("fund_backtest_", "strategy",
               ("strategy", "条件回测", "result", "strategy"),
               ("indicators", "可用指标", "indicators")),
    ],
    "futures_research": [
        *views("futures_", "contracts",
               ("main", "主力合约", "contracts_main_list"),
               ("continuous", "主连合约", "contracts_main_continuous_list"),
               ("secondary", "次主力合约", "contracts_secondary_main_list"),
               ("contracts", "合约目录", "contracts_list"),
               ("contract", "合约详情", "contracts_detail"),
               ("varieties", "品种资料", "varieties_list"),
               ("sectors", "品种板块", "variety_plates_list"),
               ("commodity-indices", "商品指数", "contracts_commodity_index_list")),
        *views("futures_", "prices",
               ("intraday", "合约分时", "prices_intraday", "price"),
               ("bars", "合约 K 线", "prices_daily", "close_price"),
               ("sessions", "交易时间轴", "calendar_session_timeline"),
               ("trading-days", "交易日历", "calendar_trading_schedule")),
        *views("futures_", "positions",
               ("variety-positions", "品种日持仓", "positions_variety_daily"),
               ("company-positions", "公司品种日持仓", "positions_company_variety_daily"),
               ("contract-positions", "合约日持仓", "positions_contract_daily"),
               ("position-history", "公司合约历史持仓", "positions_contract_historical"),
               ("companies", "期货公司", "positions_company_list")),
        *views("futures_", "basis",
               ("latest-basis", "主连基差", "basis_main_continuous_latest"),
               ("basis-history", "历史基差", "basis_historical", "close_basis"),
               ("receipts", "历史仓单", "warehouse_receipts_historical")),
    ],
    "options_research": [
        *views("options_", "contracts",
               ("contracts", "合约目录", "contracts_list"),
               ("contract", "合约与行权详情", "contracts_detail"),
               ("varieties", "期权品种", "varieties_list")),
        *views("options_", "prices",
               ("intraday", "合约分时", "prices_intraday", "price"),
               ("bars", "合约 K 线", "prices_daily", "close_price"),
               ("sessions", "交易时间轴", "calendar_session_timeline")),
    ],
}

# No public DTO or user-supplied provider name can install an adapter.
PROVIDERS = {"fuyao": fuyao_business.fetch}


def view_definition(view: View) -> dict:
    operation = fuyao_rest.OPERATIONS[view.operation]
    fields = []
    for original in operation["parameters"]:
        field = original.copy()
        name = field["name"]
        if name in {"buy_conditions", "sell_conditions"}:
            continue
        if view.id == "mainland":
            if name == "market":
                field.update(enum=["sh_sz", "bj"], default="sh_sz")
            if name == "status":
                field["enum"] = ["upcoming", "subscribable", "awaiting_listing"]
        if view.id == "calendar" and name == "status":
            field["enum"] = ["subscribable", "awaiting_listing"]
        if view.id == "bars":
            if name in {"start", "end"} and field["type"] == "integer":
                field["encoding"] = "date-ms"
            if name == "time_period":
                field.update(enum=["day_1"], default="day_1")
        fields.append(field)
    return {"id": view.id, "section": view.section, "title": view.title, "description": operation["description"],
            "fields": fields, "chart": view.chart}
