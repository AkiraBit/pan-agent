"""② 指数 K线 secid 映射:指数 secid 规则与个股不同,必须显式映射,否则相对强度永远取不到数。"""
from src.platform.marketdata.models import MarketCode


def test_get_index_klines_routes_cn_to_ftshare_and_hk_to_tencent(monkeypatch):
    from src.platform.marketdata import ftshare_market, fuyao_business
    from src.platform.marketdata.collectors import kline_collector

    calls = []

    def ftshare(code, days):
        calls.append(("ftshare", code, days))
        return []

    class _MD:
        def index_klines(self, code, *, market, days, provider):
            calls.append((provider, code, days, market))
            return []

    monkeypatch.setattr(ftshare_market, "index_bars", ftshare)
    monkeypatch.setattr(fuyao_business, "providers", lambda kind, *, market, available:
                        ["ftshare"] if market == "CN" else ["tencent"])
    monkeypatch.setattr(kline_collector, "get_market_data", lambda: _MD())
    kline_collector.get_index_klines("000300", MarketCode.CN, days=120)
    kline_collector.get_index_klines("HSI", MarketCode.HK, days=120)
    assert calls == [("ftshare", "000300", 120), ("tencent", "HSI", 120, "HK")]


def test_get_index_klines_unknown_returns_empty():
    """未映射的指数(如美股 .INX,东财K线不支持)→ 空列表,fail-soft 不抛。"""
    from src.platform.marketdata.collectors import kline_collector

    assert kline_collector.get_index_klines(".INX", MarketCode.US) == []


def test_fetch_index_context_us_failsoft():
    """美股指数无东财K线 → _fetch_index_context 返回 available False,不抛。"""
    from src.modules.research.context_builder import ContextBuilder

    ctx = ContextBuilder()._fetch_index_context(".INX", MarketCode.US)
    assert ctx.get("available") is False


def test_fetch_index_context_computes_returns(monkeypatch):
    """有指数K线时,_fetch_index_context 用收盘价算 5日/20日收益。"""
    from src.platform.marketdata.collectors import kline_collector
    from src.modules.research.context_builder import ContextBuilder

    class _K:
        def __init__(self, c):
            self.close = c

    # 25 根:从 100 等比每根 +1,最新 124;-6 根=119,-21 根=104
    closes = [_K(100 + i) for i in range(25)]
    monkeypatch.setattr(kline_collector, "get_index_klines", lambda *a, **k: closes)
    ctx = ContextBuilder()._fetch_index_context("000300", MarketCode.CN)
    assert ctx["available"] is True
    assert round(ctx["ret_5d"], 2) == round((124 - 119) / 119 * 100, 2)
    assert round(ctx["ret_20d"], 2) == round((124 - 104) / 104 * 100, 2)
