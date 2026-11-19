from src.modules.market.etf.models import EtfAnalysisMinute, EtfAnalysisCache
import asyncio
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.modules.market.api.etf import router
from src.modules.market.etf import intraday, market_stats as stats
from src.modules.market.etf import breadth_replay
from src.modules.market.etf.models import EtfIntradayDay
from src.modules.market.etf.universe import SAMPLE, UNIVERSE_KEY
from src.platform.persistence.database import Base
from src.platform.persistence.migrations import _m156_tushare_etf_market_stats, _m157_tushare_breadth_replay

DAY = date(2026, 11, 16)
NEXT = date(2026, 11, 17)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'etf-market-stats.db'}")
    Base.metadata.create_all(engine, tables=[stats.EtfIntradayDay.__table__, stats.EtfTushareUniverse.__table__])
    with engine.begin() as connection:
        EtfAnalysisMinute.__table__.create(connection, checkfirst=True)
        EtfAnalysisCache.__table__.create(connection, checkfirst=True)
        _m156_tushare_etf_market_stats(connection)
        _m156_tushare_etf_market_stats(connection)
        _m157_tushare_breadth_replay(connection)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(stats, "SessionLocal", sessions)
    monkeypatch.setattr(breadth_replay, "SessionLocal", sessions)
    yield sessions
    engine.dispose()


def moment(label, day=DAY):
    return datetime.fromisoformat(f"{day}T{label}").replace(tzinfo=intraday.CN)


def ticks(minutes, day=DAY):
    return [{"ts_code": code, "trade_time": f"{day} {minutes}:01", "pre_close": 10, "close": close, "vol": 500}
            for code, close in (("600000.SH", 12), ("000001.SZ", 8), ("920001.BJ", 10))]


def test_intraday_collection_preserves_gaps_and_api_reads_without_requesting_quotes(storage, monkeypatch):
    clock = [moment("09:30:04")]
    calls = []
    monkeypatch.setattr(intraday, "now_cn", lambda: clock[0])

    async def fetch(operation, params, fields):
        calls.append((operation, params))
        assert "trade_time" in fields
        rows = ticks("09:30")
        if clock[0].minute == 33:
            return ticks("09:33")[:-1] + ticks("09:32")[-1:]  # Beijing batch is stale
        return rows + [
            {**rows[0], "trade_time": f"{DAY} 09:30:03"},  # duplicate stock
            {**rows[0], "ts_code": "600001.SH", "trade_time": "2026-11-13 15:00:01"},
            {**rows[0], "ts_code": "600002.SH", "vol": 0},
            {**rows[0], "ts_code": "510300.SH"},
        ]

    monkeypatch.setattr(stats.tushare_market, "rows", fetch)
    for now in ("09:30:04", "09:30:04", "09:31:32", "09:33:04", "12:00:04"):
        clock[0] = moment(now)
        asyncio.run(stats.capture_breadth())
    assert stats.minute_slot(moment("09:30:04", date(2026, 11, 15))) is None
    assert stats.minute_slot(moment("13:00:04")) is None
    assert stats.minute_slot(moment("13:01:04")) == "13:01"
    assert stats.minute_slot(moment("15:00:04")) == "15:00"

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/market-stats")
        assert response.status_code == 200
        assert response.json()["breadth"] == {
            "through": "11:30", "points": {"09:30": {"up": 1, "down": 1, "flat": 1}},
        }
        assert response.json()["daily_flow"]["status"] == "pending"
        assert client.get("/market-stats", params={"date": "2026-11-13"}).json()["breadth"] == {
            "through": "15:00", "points": {},
        }
    assert calls == [("rt_k", {"ts_code": ",".join(stats.A_SHARE_GROUPS)})] * 2


def test_session_hides_future_bars_and_lunch_is_capped_at_the_morning_close(storage):
    counts = {"up": 21, "down": 13, "flat": 5}
    for minute in ("11:30", "12:00", "13:01", "13:02"):
        stats._save_breadth(DAY, minute, counts)
    assert stats.latest_due(DAY, moment("09:30:10")) is None
    assert stats.latest_due(DAY, moment("12:30:00")) == "11:30"
    assert stats.latest_due(DAY, moment("13:01:16")) == "11:30"
    assert stats.latest_due(DAY, moment("13:01:17")) == "13:01"
    assert stats.read_session(DAY, moment("12:30:00"))["breadth"] == {
        "through": "11:30", "points": {"11:30": counts},
    }
    # A successful automatic capture may be ready before the missing-minute grace expires.
    assert stats.read_session(DAY, moment("13:01:08"))["breadth"] == {
        "through": "13:01", "points": {"11:30": counts, "13:01": counts},
    }


def test_daily_net_uses_the_current_main_chart_basket_and_waits_for_full_coverage(storage, monkeypatch):
    clock = [moment("08:34:59", NEXT)]
    monkeypatch.setattr(intraday, "now_cn", lambda: clock[0])
    calls = []
    complete = [False]
    members = SAMPLE[:3]
    with storage.begin() as db:
        db.add(EtfIntradayDay(trade_date=DAY.isoformat(), parts={
            "members": list(members), "universe_key": UNIVERSE_KEY, "parts": {},
        }))

    async def fetch(operation, params, fields):
        calls.append(params["trade_date"])
        assert operation == "etf_share_size"
        rows = [
            {"ts_code": symbol, "trade_date": params["trade_date"], "total_share": 100 + change,
             "nav": nav}
            for symbol, change, nav in zip((*members, SAMPLE[3]), (2, -3, 0, 400), (3, 4, 1, 10))
        ]
        if params["trade_date"] == "20261113":
            return [{**row, "total_share": 100, "nav": None} for row in rows]
        return rows if complete[0] else rows[:1]

    monkeypatch.setattr(stats.tushare_market, "rows", fetch)
    asyncio.run(stats.capture_daily_flows())
    assert not calls
    clock[0] = moment("08:35:00", NEXT)
    asyncio.run(stats.capture_daily_flows())
    assert stats.read_session(DAY, clock[0])["daily_flow"] == {
        "status": "partial", "total": 3, "covered": 1, "net_cny": None,
    }
    complete[0] = True
    asyncio.run(stats.capture_daily_flows())
    asyncio.run(stats.capture_daily_flows())
    assert calls == ["20261116", "20261113", "20261116"]
    assert stats.read_session(DAY, clock[0])["daily_flow"] == {
        "status": "ready", "total": 3, "covered": 3, "net_cny": -60_000.0,
    }
    assert stats.read_session(NEXT, clock[0])["daily_flow"]["total"] == len(SAMPLE) == 22
