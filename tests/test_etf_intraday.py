import asyncio
from datetime import date, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.modules.administration.api.auth import get_current_user
from src.modules.market.api import etf as api
from src.modules.market.etf import intraday as m
from src.platform.persistence.database import Base
from src.platform.persistence.migrations import (
    _m151_replace_legacy_etf, _m152_tushare_etf_cache, _m153_tushare_turnover_baselines, _m154_tushare_etf_price_sessions,
    _m155_tushare_index_price_sessions,
)


DAY = date(2026, 11, 16)
TODAY = date(2026, 11, 17)
FUNDS = ("510300.SH", "510330.SH")
NAMES = dict(zip(FUNDS, ("华泰柏瑞沪深300ETF", "华夏沪深300ETF")))
BENCHMARKS = [{"ts_code": "000300.SH", "bmk_type": "宽基"},
              {"ts_code": "000922.CSI", "bmk_type": "策略"}]
LISTINGS = [{"ts_code": code, "index_code": "000300.SH", "list_status": "L", "etf_type": "纯境内", "list_date": "20130101"}
            for code in (*FUNDS, "510350.SH")]
for listing in LISTINGS:
    listing["csname"] = NAMES.get(listing["ts_code"])
LISTINGS += [
    {**LISTINGS[0], "ts_code": "159919.SZ", "etf_type": "QDII"},
    {**LISTINGS[0], "ts_code": "159845.SZ", "index_code": "000922.CSI"},
]


def build_payload(operation, params, day, minute="09:31"):
    if operation == "etf_basic":
        return LISTINGS
    if operation == "mkt_idx_bmk":
        return BENCHMARKS
    if operation == "index_daily":
        end = datetime.strptime(params["end_date"], "%Y%m%d").date()
        end = end - timedelta(days=2) if end.weekday() == 6 else end
        return [{"ts_code": m.INDEX, "trade_date": end.strftime("%Y%m%d"), "close": 3575.25}]
    values = [{"ts_code": symbol, "trade_time" if not operation.startswith("rt_") else "time": f"{day} {label}:00",
               "close": "3580.25", "amount": 25_000_000 if symbol == FUNDS[0] else 125_000_000}
              for symbol in params["ts_code"].split(",")
              for label in ([minute] if operation in {"rt_idx_min", "rt_etf_min"} else ["09:30", minute])]
    return values


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'intraday.db'}")
    Base.metadata.create_all(engine, tables=[m.EtfIntradayDay.__table__, m.EtfTushareUniverse.__table__,
                                             m.EtfTurnoverBaseline.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(m, "SessionLocal", sessions)
    monkeypatch.setattr(m, "now_cn", lambda: datetime(2026, 11, 17, 9, 31, tzinfo=m.CN))
    yield sessions
    engine.dispose()


def test_catalog_cross_checks_benchmarks_without_enrolling_every_broad_market_fund():
    chi_next = {**LISTINGS[0], "ts_code": "159949.SZ", "index_code": "399673.SZ",
                "csname": "华安创业板50ETF", "list_date": "20160722"}
    assert m.market_universe([*LISTINGS, chi_next], BENCHMARKS) == {
        "broad_count": 3, "listed": {**dict.fromkeys(FUNDS, "2013-01-01"), "159949.SZ": "2016-07-22"},
        "names": {**NAMES, "159949.SZ": "华安创业板50ETF"},
    }
    assert "159949.SZ" not in m.market_universe([*LISTINGS, {**chi_next, "index_code": "000922.CSI"}], BENCHMARKS)["listed"]


def test_cold_history_is_coalesced_and_source_isolated(db, monkeypatch):
    calls = []

    async def fetch(operation, params, fields):
        calls.append((operation, params, fields))
        return build_payload(operation, params, DAY, "15:00")

    with db.begin() as session:
        session.execute(text("CREATE TABLE etf_intraday_days(trade_date VARCHAR PRIMARY KEY, parts JSON)"))
        session.execute(text("""INSERT INTO etf_intraday_days VALUES ('2026-11-16', '{"members":["159915.SZ"],"source":"ftshare"}')"""))
    monkeypatch.setattr(m.tushare_market, "rows", fetch)

    async def run():
        store = m.IntradayStore()
        results = await asyncio.gather(*(store.load(DAY) for _ in range(4)))
        assert sum(not row["cached"] for row in results) == 1
        new_store = m.IntradayStore()
        cached = await new_store.load(DAY, refresh=True)
        assert cached["source"] == "tushare" and cached["archived"] and cached["cached"]
        assert cached["symbols"] == list(FUNDS) and cached["broad_count"] == 3
        assert set(cached["disclosures"]) == set(FUNDS) and cached["names"] == NAMES
        assert cached["previous_close"] == 3575.25 and cached["previous_close_date"] == "2026-11-13"
        assert cached["points"] == [
            {"minute": "09:30", "turnover_cny": 150_000_000, "etf_count": 2, "index_close": 3580.25},
            {"minute": "15:00", "turnover_cny": 150_000_000, "etf_count": 2, "index_close": 3580.25},
        ]
    asyncio.run(run())

    assert sorted(op for op, _, _ in calls) == [
        "etf_basic", "etf_mins", "etf_mins", "idx_mins", "index_daily", "mkt_idx_bmk",
    ]
    assert [params["ts_code"] for op, params, _ in calls if op == "etf_mins"] == list(FUNDS)
    assert all(params["start_date"] == "2026-11-16 09:30:00" and params["end_date"] == "2026-11-16 15:00:00"
               for op, params, _ in calls if op in {"etf_mins", "idx_mins"})


def test_expands_saved_watchlist_without_refetching_archived_sources(db, monkeypatch):
    extra, not_listed_yet = "159361.SZ", "588000.SH"
    original = {code: {"data": {"09:30": 1}, "mode": "archive"} for code in FUNDS}
    original[m.INDEX] = {"data": {"09:30": 3580.25}, "mode": "archive"}
    original["reference"] = {"data": {"date": "2026-11-13", "close": 3575.25}, "mode": "archive"}
    with db.begin() as session:
        session.add(m.EtfIntradayDay(trade_date=DAY.isoformat(), parts={
            "universe_key": "tushare-broad-watchlist-v2", "members": list(FUNDS), "broad_count": 3, "parts": original,
        }))
    calls = []

    async def fetch(operation, params, _fields):
        calls.append((operation, params))
        if operation == "etf_basic":
            return LISTINGS + [
                {**LISTINGS[0], "ts_code": extra, "csname": "易方达中证A500ETF"},
                {**LISTINGS[0], "ts_code": not_listed_yet, "list_date": "20261117"},
            ]
        return build_payload(operation, params, DAY)

    monkeypatch.setattr(m.tushare_market, "rows", fetch)

    async def run():
        store = m.IntradayStore()
        upgraded = await store.load(DAY)
        assert upgraded["archived"] and upgraded["symbols"] == [*FUNDS, extra]
        assert set(upgraded["disclosures"]) == set(FUNDS)
        assert upgraded["names"] == {**NAMES, extra: "易方达中证A500ETF"}
        assert upgraded["points"][0]["etf_count"] == 3
        count = len(calls)
        assert (await store.load(DAY, refresh=True))["cached"] and len(calls) == count

    asyncio.run(run())
    assert [operation for operation, _ in calls] == ["etf_basic", "mkt_idx_bmk", "etf_mins"]
    assert calls[-1][1]["ts_code"] == extra
    with db() as session:
        parts = session.get(m.EtfIntradayDay, DAY.isoformat()).parts["parts"]
        assert all(parts[key] == value for key, value in original.items())


def test_live_batches_adjacent_bars_and_archives_individual_components(db, monkeypatch):
    current = datetime(2026, 11, 17, 9, 31, tzinfo=m.CN)
    monkeypatch.setattr(m, "now_cn", lambda: current)
    calls = []
    empty = True

    async def fetch(operation, params, _fields):
        calls.append(operation)
        if operation == "idx_mins" and empty:
            return []
        minute = "15:00" if operation in {"idx_mins", "etf_mins"} else current.strftime("%H:%M")
        return build_payload(operation, params, TODAY, minute)

    monkeypatch.setattr(m.tushare_market, "rows", fetch)

    async def run():
        nonlocal current, empty
        store = m.IntradayStore()
        live = await store.load(None)
        assert live["status"] == "live" and live["points"][-1]["minute"] == "09:31"
        assert calls.count("rt_etf_min_daily") == len(FUNDS)
        assert (await store.load(TODAY, refresh=True))["cached"]
        current += timedelta(seconds=61)
        assert (await store.load(TODAY))["cached"]
        count = len(calls)
        refreshed = await store.load(TODAY, refresh=True)
        assert refreshed["points"][-1]["minute"] == "09:32"
        assert calls[count:] == ["rt_etf_min", "rt_idx_min"]
        current = current.replace(hour=21)
        partial = await store.load(TODAY)
        assert not partial["archived"] and partial["issues"] == ["unavailable"]
        assert next(p for p in partial["points"] if p["minute"] == "09:32")["index_close"] == 3580.25
        current += timedelta(minutes=4)
        empty = False
        count = len(calls)
        assert (await store.load(TODAY))["archived"]
        assert calls[count:] == ["idx_mins"]
    asyncio.run(run())


def test_rate_limit_then_retry_only_missing_etf(db, monkeypatch):
    current = datetime(2026, 11, 17, 10, tzinfo=m.CN)
    monkeypatch.setattr(m, "now_cn", lambda: current)
    failed = True
    calls = []

    async def fetch(operation, params, _fields):
        calls.append((operation, params))
        if failed and operation == "etf_mins" and params["ts_code"] == FUNDS[1]:
            raise m.TushareFailure("rate_limited", retry_after=60)
        return build_payload(operation, params, DAY)

    monkeypatch.setattr(m.tushare_market, "rows", fetch)

    async def run():
        nonlocal failed, current
        store = m.IntradayStore()
        first = await store.load(DAY)
        assert first["etf_count"] == 1 and first["issues"] == ["rate_limited"]
        count = len(calls)
        assert (await store.load(date(2026, 11, 13)))["issues"] == ["rate_limited"]
        assert len(calls) == count
        current += timedelta(minutes=4)
        failed = False
        healed = await store.load(DAY, refresh=True)
        assert healed["archived"] and healed["etf_count"] == 2
        assert [(op, params["ts_code"]) for op, params in calls[count:]] == [("etf_mins", FUNDS[1])]
    asyncio.run(run())


def test_refresh_uses_minute_slots_and_keeps_cached_bars_when_the_source_is_late(db, monkeypatch):
    current = datetime(2026, 11, 17, 9, 34, 45, tzinfo=m.CN)
    monkeypatch.setattr(m, "now_cn", lambda: current)
    calls = []
    published = "09:34"

    async def fetch(operation, params, _fields):
        calls.append(operation)
        return build_payload(operation, params, TODAY, published)

    monkeypatch.setattr(m.tushare_market, "rows", fetch)

    async def run():
        nonlocal current, published
        store = m.IntradayStore()
        assert (await store.load(TODAY))["points"][-1]["minute"] == "09:34"
        calls.clear()
        current = current.replace(minute=35, second=12)
        delayed = await store.load(TODAY, refresh=True)
        assert delayed["points"][-1]["minute"] == "09:34"
        assert calls == ["rt_etf_min", "rt_idx_min"]
        current = current.replace(second=16)
        assert (await store.load(TODAY, refresh=True))["cached"]
        assert len(calls) == 2
        current = current.replace(minute=36, second=18)
        published = "09:35"
        assert (await store.load(TODAY, refresh=True))["points"][-1]["minute"] == "09:35"

    asyncio.run(run())


def test_wrong_date_and_lunch_are_not_plotted():
    with pytest.raises(m.TushareFailure):
        m.minute_series([{"ts_code": m.INDEX, "time": f"{TODAY} 09:31:00", "close": 3}], DAY, m.INDEX, "close", live=True)
    assert m.minute_series([{"ts_code": m.INDEX, "trade_time": f"{DAY} 12:00:00", "close": 3}], DAY, m.INDEX, "close") == {}


def test_turnover_baseline_batches_missing_sessions_and_reuses_the_same_basket(db, monkeypatch):
    calls = []
    days = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"]
    new_day = "2026-11-09"
    store = m.IntradayStore()
    saved = {"data": dict.fromkeys(m.MINUTES, 10), "mode": "archive"}
    selected = {"universe_key": m.UNIVERSE_KEY, "members": list(FUNDS)}
    store._save(TODAY, {**selected, "parts": {
        **dict.fromkeys(FUNDS, saved), m.INDEX: saved,
        "reference": {"data": {"close": 3600, "date": DAY.isoformat()}, "mode": "archive"},
    }})
    for key in days:
        store._save(date.fromisoformat(key), {**(selected if key == days[-1] else {}), "parts": {
            FUNDS[0]: saved, "159952.SZ": {"data": dict.fromkeys(m.MINUTES, 1e9), "mode": "archive"},
            **({FUNDS[1]: saved} if key == days[-1] else {}),
        }})

    async def fetch(operation, params, _fields):
        symbol = params["ts_code"]
        assert operation == "etf_mins" and symbol in FUNDS
        start, end = params["start_date"][:10], params["end_date"][:10]
        calls.append((symbol, start, end))
        return [{"ts_code": symbol, "trade_time": f"{key} {minute}:00", "amount": 10 if symbol == FUNDS[0] else 20}
                for key in (new_day, *days) if start <= key <= end for minute in m.MINUTES]

    monkeypatch.setattr(m.tushare_market, "rows", fetch)

    async def run():
        assert (await store.load(TODAY))["turnover_baseline"] == {"status": "needs_calculation"}
        assert not calls
        first, second = await asyncio.gather(store.turnover_baseline(TODAY), store.turnover_baseline(TODAY))
        assert first == second
        assert first["sessions"] == 5
        cumulative = first["cumulative_cny"]
        assert cumulative["09:31"] == 56 and cumulative["15:00"] == 28 * 241
        assert "12:00" not in cumulative
        with db() as session:
            stored = session.get(m.EtfTurnoverBaseline, TODAY.isoformat()).payload
            assert stored["result"] == first and stored["basis"]["days"] == days

        restarted = m.IntradayStore()
        with monkeypatch.context() as patch:
            def unexpected_history(_days):
                pytest.fail("A valid stored baseline should not load the source minute rows")
            patch.setattr(restarted, "_read_baseline_inputs", unexpected_history)
            assert await restarted.turnover_baseline(TODAY) == first
            assert (await restarted.load(TODAY))["turnover_baseline"] == {"status": "ready", "value": first}

        shifted = await restarted.turnover_baseline(DAY)
        assert shifted["cumulative_cny"]["15:00"] == 30 * 241
        with db() as session:
            assert session.get(m.EtfTurnoverBaseline, DAY.isoformat()).payload["basis"]["days"] == [new_day, *days[:-1]]

        corrected = store._read(DAY)
        corrected["parts"][FUNDS[1]]["data"]["09:30"] = 15
        store._save(DAY, corrected)
        assert (await restarted.load(TODAY))["turnover_baseline"] == {"status": "needs_calculation"}
        recalculated = await restarted.turnover_baseline(TODAY)
        assert recalculated["cumulative_cny"]["15:00"] == 28 * 241 + 1
        assert (await restarted.turnover_baseline(DAY)) == shifted

    asyncio.run(run())
    assert calls[0] == (FUNDS[1], "2026-11-10", "2026-11-13")
    assert set(calls[1:]) == {(symbol, new_day, new_day) for symbol in FUNDS} and len(calls) == 3


def test_partial_history_is_saved_and_completed_without_redownloading_other_days(db, monkeypatch):
    store = m.IntradayStore()
    store._save(TODAY, {"universe_key": m.UNIVERSE_KEY, "members": [FUNDS[0]]})
    days = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"]
    missing = days[2]
    calls = []

    async def fetch(operation, params, _fields):
        assert operation == "etf_mins"
        start, end = params["start_date"][:10], params["end_date"][:10]
        calls.append((start, end))
        return [{"ts_code": FUNDS[0], "trade_time": f"{key} {minute}:00", "amount": 10}
                for key in days if start <= key <= end for minute in m.MINUTES
                if (key != missing and len(calls) == 1) or (key == missing and (minute == "09:30") == (len(calls) == 1))]

    monkeypatch.setattr(m.tushare_market, "rows", fetch)

    async def run():
        assert await store.turnover_baseline(TODAY) is None
        partial = store._read(date.fromisoformat(missing))["parts"][FUNDS[0]]
        assert partial["data"] == {"09:30": 10}
        with db() as session:
            assert session.get(m.EtfTurnoverBaseline, TODAY.isoformat()) is None
        result = await m.IntradayStore().turnover_baseline(TODAY)
        assert result["cumulative_cny"]["15:00"] == 10 * 241

    asyncio.run(run())
    assert calls == [(days[0], days[-1]), (missing, missing)]


def test_api_is_protected_and_retires_old_routes(db, monkeypatch):
    monkeypatch.setattr("src.modules.administration.api.auth.get_password_hash", lambda _db: "configured")
    monkeypatch.setattr(m, "store", m.IntradayStore())
    app = FastAPI()
    app.include_router(api.router, prefix="/api/etf", dependencies=[Depends(get_current_user)])
    with TestClient(app) as client:
        assert client.get("/api/etf/intraday").status_code == 401
        assert client.get("/api/etf/turnover-baseline?date=2026-11-17").status_code == 401
        assert client.get("/api/etf/price-catalog?q=515220").status_code == 401
        assert client.get("/api/etf/price-line?date=2026-11-17&symbol=515220.SH").status_code == 401
        app.dependency_overrides[get_current_user] = lambda: "test"
        assert client.get("/api/etf/intraday?date=2099-11-17").status_code == 422
        assert client.get("/api/etf/intraday?date=2026-11-31").status_code == 422
        assert client.get("/api/etf/turnover-baseline?date=2026-11-17").json() is None
        assert client.get("/api/etf/price-catalog").json() == {"items": [], "issue": None}
        assert client.get("/api/etf/price-line?date=2026-11-17&symbol=invalid").status_code == 422
        assert client.get("/api/etf/price-catalog?kind=stock").status_code == 422
        closed = client.get("/api/etf/intraday?date=2026-11-15").json()
        assert closed["status"] == "closed" and closed["source"] == "tushare"
        assert closed["market"] == {"at": "2026-11-17T09:31:00.000+08:00", "date": "2026-11-17",
                                    "timezone": "Asia/Shanghai", "trading_day": True,
                                    "next_trading_day": "2026-11-18"}
        for route in ("board", "history", "dates", "national-team", "observations"):
            assert client.get(f"/api/etf/{route}").status_code == 404


def test_legacy_cleanup_and_provider_migration_use_different_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE etf_source_snapshots(id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO etf_source_snapshots VALUES (1)"))
        conn.execute(text("CREATE TABLE positions(code VARCHAR)"))
        conn.execute(text("INSERT INTO positions VALUES ('510300')"))
        _m151_replace_legacy_etf(conn)
        conn.execute(text("INSERT INTO etf_intraday_days VALUES ('2026-11-16','{}')"))
        _m152_tushare_etf_cache(conn)
        _m152_tushare_etf_cache(conn)
        conn.execute(text("INSERT INTO etf_tushare_intraday_days VALUES ('2026-11-16','{}')"))
        _m153_tushare_turnover_baselines(conn)
        _m153_tushare_turnover_baselines(conn)
        _m154_tushare_etf_price_sessions(conn)
        _m154_tushare_etf_price_sessions(conn)
        _m155_tushare_index_price_sessions(conn)
        _m155_tushare_index_price_sessions(conn)
        assert set(inspect(conn).get_table_names()) == {
            "positions", "etf_intraday_days", "etf_tushare_intraday_days", "etf_tushare_universes",
            "etf_tushare_turnover_baselines",
            "etf_tushare_price_sessions",
            "etf_tushare_index_price_sessions",
        }
        assert conn.scalar(text("SELECT code FROM positions")) == "510300"
        assert conn.scalar(text("SELECT trade_date FROM etf_intraday_days")) == "2026-11-16"
        assert conn.execute(text("SELECT trade_date, parts, turnover_revision FROM etf_tushare_intraday_days")).one() == (
            "2026-11-16", "{}", 0,
        )
    engine.dispose()
