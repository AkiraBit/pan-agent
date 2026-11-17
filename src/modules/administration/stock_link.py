"""股票外部链接生成工具：根据股票代码、市场和用户选择的平台生成行情页 URL。

全局设置 key: stock_link_platform (默认 eastmoney)
"""

from __future__ import annotations

from src.platform.persistence.database import SessionLocal
from src.platform.persistence.models import AppSettings

# 支持的平台 {code: 中文名}
PLATFORMS = {
    "eastmoney": "东方财富",
}

DEFAULT_PLATFORM = "eastmoney"
SETTING_KEY = "stock_link_platform"


def get_platform() -> str:
    """从 AppSettings 读取当前配置的平台代码。"""
    db = SessionLocal()
    try:
        row = db.query(AppSettings).filter(AppSettings.key == SETTING_KEY).first()
        return row.value if row and row.value in PLATFORMS else DEFAULT_PLATFORM
    finally:
        db.close()


def stock_url(symbol: str, market: str, platform: str = "") -> str:
    """生成股票行情页 URL。

    Args:
        symbol: 股票代码，如 "002837", "AAPL", "00883"
        market: 市场代码，如 "CN", "US", "HK"
        platform: 兼容旧通知模板，链接统一使用东方财富。
    """
    # Old templates may contain a retired platform code; use the retained quote site.
    from src.platform.marketdata.cn_symbol import get_cn_prefix

    market = market.upper()
    if market in {"HK", "US"}:
        path = f"{market.lower()}/{symbol}"
    else:
        prefix = get_cn_prefix(symbol)
        path = f"bj/{symbol}" if prefix == "bj" else f"{prefix}{symbol}"
    return f"https://quote.eastmoney.com/{path}.html"


def stock_link_markdown(symbol: str, market: str, platform: str = "") -> str:
    """生成 Markdown 格式的股票链接: [002837.CN](https://quote.eastmoney.com/sz002837.html)"""
    code = f"{symbol}.{market}"
    url = stock_url(symbol, market, platform)
    return f"[{code}]({url})"
