import asyncio
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.modules.market.etf import intraday, prices
from src.platform.persistence.database import Base


CODE = "515220.SH"
DAY = date(2026, 11, 17)


def test_price_catalog_and_intraday_prices_survive_restart_and_only_append_the_new_minute(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'prices.db'}")
    Base.metadata.create_all(engine, tables=[prices.EtfPriceSession.__table__, prices.EtfTushareUniverse.__table__])
    monkeypatch.setattr(prices, "SessionLocal", sessionmaker(bind=engine))
    now = datetime(2026, 11, 17, 9, 31, 12, tzinfo=intraday.CN)
    monkeypatch.setattr(intraday, "now_cn", lambda: now)
    calls = []

    async def query(operation, params, fields=""):
        calls.append(operation)
        if operation == "etf_basic":
            return [{"ts_code": CODE, "csname": "国泰中证煤炭ETF", "list_status": "L", "list_date": "20200302"}, *[
                {"ts_code": f"{515221 + i}.SH", "csname": f"宽基{i}ETF", "list_status": "L", "list_date": "20200302"}
                for i in range(26)
            ]]
        minutes = {"rt_etf_min_daily": ["09:30", "09:31"], "rt_etf_min": ["09:32"]}[operation]
        return [{"ts_code": CODE, "time": f"{DAY} {minute}:00", "close": "1.250"} for minute in minutes]

    monkeypatch.setattr(intraday.store, "_query", query)

    async def run():
        nonlocal now
        store = prices.EtfPriceStore()
        assert await store.search(" ") == {"items": [], "issue": None}
        all_items = await store.search("", include_all=True)
        assert len(all_items["items"]) == 27 and all_items["items"][0]["symbol"] == CODE
        assert len((await store.search("ETF", include_all=True))["items"]) == 27
        assert len((await store.search("ETF"))["items"]) == 24
        matched = await store.search("煤炭")
        assert matched["items"] == [{"symbol": CODE, "name": "国泰中证煤炭ETF"}]
        assert await store.search("515220") == matched
        assert await store.search("５１５２２０．ｓｈ") == matched
        first, second = await asyncio.gather(store.load(DAY, CODE), store.load(DAY, CODE))
        assert first == second and first["complete"]
        assert first["closes"] == {"09:30": 1.25, "09:31": 1.25}
        fresh = prices.EtfPriceStore()
        assert await fresh.load(DAY, CODE) == first
        now = now.replace(minute=32)
        new = await fresh.load(DAY, CODE)
        assert new["complete"] and new["closes"] == {**first["closes"], "09:32": 1.25}
        assert await store.load(DAY, CODE) == new

    asyncio.run(run())
    assert calls == ["etf_basic", "rt_etf_min_daily", "rt_etf_min"]
    engine.dispose()


def test_archived_prices_request_only_missing_minute_ranges(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(engine, tables=[prices.EtfPriceSession.__table__])
    monkeypatch.setattr(prices, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(intraday, "now_cn", lambda: datetime(2026, 11, 18, 10, tzinfo=intraday.CN))
    store = prices.EtfPriceStore()
    missing = ("09:31", "14:50")
    closes = {minute: 1.25 for minute in intraday.MINUTES if minute not in missing}
    store._save(DAY, CODE, {"closes": closes, "validated": True})
    calls = []

    async def query(operation, params, fields=""):
        assert operation == "etf_mins"
        assert params["start_date"] == params["end_date"]
        calls.append(params["start_date"])
        return [{"ts_code": CODE, "trade_time": params["start_date"], "close": 1.26}]

    monkeypatch.setattr(intraday.store, "_query", query)

    async def run():
        filled = await store.load(DAY, CODE)
        assert filled["complete"] and filled["closes"] == {**closes, **dict.fromkeys(missing, 1.26)}
        assert await prices.EtfPriceStore().load(DAY, CODE) == filled

    asyncio.run(run())
    assert calls == [f"{DAY} {minute}:00" for minute in missing]
    engine.dispose()


def test_index_catalog_and_minute_cache_are_separate_from_etfs(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'instruments.db'}")
    Base.metadata.create_all(engine, tables=[prices.EtfPriceSession.__table__, prices.IndexPriceSession.__table__,
                                             prices.EtfTushareUniverse.__table__])
    monkeypatch.setattr(prices, "SessionLocal", sessionmaker(bind=engine))
    now = datetime(2026, 11, 17, 9, 31, 12, tzinfo=intraday.CN)
    monkeypatch.setattr(intraday, "now_cn", lambda: now)
    code = "000688.SH"
    calls = []

    async def query(operation, params, fields=""):
        calls.append((operation, params.get("market")))
        if operation == "index_basic":
            if params["market"] == "SSE":
                return [{"ts_code": code, "name": "科创50", "list_date": "20200723"}]
            return [{"ts_code": "399006.SZ", "name": "创业板指", "list_date": "20100601"}]
        if operation == "rt_idx_min_daily":
            return [{"ts_code": code, "time": f"{DAY} {minute}:00", "close": close}
                    for minute, close in (("09:31", 1210), ("09:30", 1200), ("09:30", 1199))]
        assert operation == "rt_idx_min"
        return [{"ts_code": code, "time": f"{DAY} 09:32:00", "close": 1220}]

    monkeypatch.setattr(intraday.store, "_query", query)

    async def run():
        nonlocal now
        etfs, index = prices.EtfPriceStore(), prices.EtfPriceStore("index")
        etfs._save(DAY, code, {"closes": {"09:30": 1, "09:31": 1.01}, "validated": True})
        listing = await index.search("", include_all=True)
        assert [row["kind"] for row in listing["items"]] == ["index", "index"]
        assert (await index.search("科创50"))["items"] == [{"symbol": code, "name": "科创50", "kind": "index"}]
        assert (await index.load(DAY, CODE))["issue"] == "unknown_index"
        first = await index.load(DAY, code)
        assert first["kind"] == "index" and first["closes"] == {"09:30": 1200, "09:31": 1210}
        assert (await etfs.load(DAY, code))["closes"] == {"09:30": 1, "09:31": 1.01}
        assert await prices.EtfPriceStore("index").load(DAY, code) == first
        now = now.replace(minute=32)
        assert (await index.load(DAY, code))["closes"]["09:32"] == 1220

    asyncio.run(run())
    assert calls == [("index_basic", "SSE"), ("index_basic", "SZSE"), ("rt_idx_min_daily", None), ("rt_idx_min", None)]
    engine.dispose()
