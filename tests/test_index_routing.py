"""指数取数(K线 + market.py /indices)路由测试"""
import asyncio

import src.platform.marketdata.collectors.kline_collector as kc
import src.modules.market.api.market as mkt


def test_get_index_klines_switches_from_ftshare_to_fuyao_and_converts_bars(monkeypatch):
    from marketdata.types import Bar
    from src.platform.marketdata import ftshare_market, fuyao_business, fuyao_native

    calls = []

    def ftshare(code, days):
        calls.append(("ftshare", code, days))
        return []

    def fuyao(code, days):
        calls.append(("fuyao", code, days))
        return [Bar(date="2026-07-01", open=3180.0, close=3200.0, high=3210.0, low=3170.0, volume=1e8)]

    monkeypatch.setattr(fuyao_business, "providers", lambda kind, *, market, available: ["ftshare", "fuyao"])
    monkeypatch.setattr(ftshare_market, "index_bars", ftshare)
    monkeypatch.setattr(fuyao_native, "index_klines", fuyao)

    out = kc.get_index_klines("000001", kc.MarketCode.CN, days=120)

    assert calls == [("ftshare", "000001", 120), ("fuyao", "000001", 120)]
    assert len(out) == 1 and isinstance(out[0], kc.KlineData)
    assert out[0].date == "2026-07-01" and out[0].close == 3200.0


def test_get_market_indices_uses_marketdata(monkeypatch):
    """/indices 走 md.index_quotes;quote_map/response_symbol 匹配逻辑与返回字段不变。"""
    captured: dict = {}

    class _MD:
        def index_quotes(self, tencent_symbols):
            captured["symbols"] = list(tencent_symbols)
            return [
                {
                    "symbol": "000001",
                    "name": "上证指数",
                    "current_price": 3200.0,
                    "change_pct": 0.63,
                    "change_amount": 20.0,
                    "prev_close": 3180.0,
                },
            ]

    monkeypatch.setattr(mkt, "get_market_data", lambda: _MD())
    # spark 取数不是本用例关注点,桩掉避免真实联网(见 test_market_indices_spark.py 专测 spark)。
    monkeypatch.setattr(mkt, "get_index_klines", lambda *a, **k: [])

    out = asyncio.run(mkt.get_market_indices())

    assert captured["symbols"] == [idx["tencent_symbol"] for idx in mkt.MARKET_INDICES]
    sh = next(i for i in out if i["symbol"] == "000001")
    assert sh["current_price"] == 3200.0 and sh["change_pct"] == 0.63
    # 未命中行情的指数仍返回基本信息占位(current_price=None),匹配逻辑不变
    hsi = next(i for i in out if i["symbol"] == "HSI")
    assert hsi["current_price"] is None
