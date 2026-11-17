"""tests for src/core/stock_link.py

所有测试显式传入 platform 参数，避免访问数据库。
"""

from __future__ import annotations

from src.modules.administration.stock_link import stock_url, stock_link_markdown


class TestStockUrl:
    def test_cn_sz(self):
        """股票链接 — CN 深圳股票"""
        url = stock_url("002837", "CN", platform="eastmoney")
        assert url == "https://quote.eastmoney.com/sz002837.html"

    def test_cn_sh(self):
        """股票链接 — CN 上海股票"""
        url = stock_url("600519", "CN", platform="eastmoney")
        assert url == "https://quote.eastmoney.com/sh600519.html"

    def test_cn_bj(self):
        """股票链接 — CN 北交所股票"""
        url = stock_url("830799", "CN", platform="eastmoney")
        assert url == "https://quote.eastmoney.com/bj/830799.html"

    def test_us(self):
        """股票链接 — US 美股"""
        url = stock_url("AAPL", "US", platform="eastmoney")
        assert url == "https://quote.eastmoney.com/us/AAPL.html"

    def test_hk(self):
        """股票链接 — HK 港股"""
        url = stock_url("00883", "HK", platform="eastmoney")
        assert url == "https://quote.eastmoney.com/hk/00883.html"

    def test_market_case_insensitive(self):
        """股票链接 — 市场代码不区分大小写"""
        url = stock_url("002837", "cn", platform="eastmoney")
        assert url == "https://quote.eastmoney.com/sz002837.html"


class TestStockLinkMarkdown:
    def test_cn(self):
        """Markdown 链接 — CN 格式"""
        md = stock_link_markdown("002837", "CN", platform="eastmoney")
        assert md == "[002837.CN](https://quote.eastmoney.com/sz002837.html)"

    def test_us(self):
        """Markdown 链接 — US 格式"""
        md = stock_link_markdown("AAPL", "US", platform="eastmoney")
        assert md == "[AAPL.US](https://quote.eastmoney.com/us/AAPL.html)"
