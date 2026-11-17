"""新闻数据结构 + 聚合采集器薄 shim。

抓取逻辑在 marketdata 包；本模块为消费方保留 NewsItem 和 NewsCollector。
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsItem:
    """新闻数据结构"""
    source: str           # 服务商标识
    external_id: str      # 来源侧唯一ID
    title: str
    content: str
    publish_time: datetime
    symbols: list[str] = field(default_factory=list)  # 关联股票代码
    importance: int = 0   # 0-3 重要性
    url: str = ""         # 原文链接


class NewsCollector:
    """聚合新闻采集器 —— 薄 shim，实际抓取/聚合/去重逻辑已收口进 marketdata 包。"""

    @classmethod
    def from_database(cls) -> "NewsCollector":
        """配置现由包内 DbConfigProvider 按需读 DataSource 表，这里直接返回实例。"""
        return cls()

    async def fetch_all(
        self,
        symbols: list[str] | None = None,
        since_hours: int = 2,
        symbol_names: dict[str, str] | None = None,
    ) -> list[NewsItem]:
        """
        聚合所有已启用新闻数据源的新闻（聚合/去重/排序均在 marketdata 包内完成）。

        Args:
            symbols: 股票代码列表
            since_hours: 获取最近 N 小时的新闻（公告类源的窗口由包内自动放宽）
            symbol_names: 股票代码到名称的映射（可选，eastmoney_news 用名称搜索效果更好）

        Returns:
            按时间倒序排列的新闻列表
        """
        from src.platform.marketdata.marketdata_client import md_news

        return await asyncio.to_thread(md_news, symbols or [], since_hours, symbol_names)
