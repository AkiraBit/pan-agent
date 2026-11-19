from src.modules.market.etf.models import EtfAnalysisMinute, EtfAnalysisCache
import asyncio
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.modules.market.api.etf import router
from src.modules.market.etf import breadth_replay as replay, intraday, market_stats
from src.platform.marketdata.tushare_market import TushareFailure
from src.platform.persistence.migrations import _m156_tushare_etf_market_stats, _m157_tushare_breadth_replay

DAY = date(2026, 11, 16)
TODAY = date(2026, 11, 17)
SYMBOLS = ("600000.SH", "000001.SZ", "920001.BJ")


@pytest.fixture
def replay_storage(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    with engine.begin() as connection:
        EtfAnalysisMinute.__table__.create(connection, checkfirst=True)
        EtfAnalysisCache.__table__.create(connection, checkfirst=True)
        _m156_tushare_etf_market_stats(connection)
        _m157_tushare_breadth_replay(connection)
        _m157_tushare_breadth_replay(connection)
        market_stats.EtfIntradayDay.__table__.create(connection)
        market_stats.EtfTushareUniverse.__table__.create(connection)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(replay, "SessionLocal", sessions)
    monkeypatch.setattr(market_stats, "SessionLocal", sessions)
    yield sessions
    engine.dispose()


def test_manual_backfill_only_fills_gaps_and_reuses_persisted_bars(replay_storage, monkeypatch):
    monkeypatch.setattr(intraday, "now_cn", lambda: datetime(2026, 11, 17, 22, tzinfo=intraday.CN))
    monkeypatch.setattr(replay, "REQUESTS_PER_SECOND", 1000)
    with replay_storage.begin() as db:
        db.add_all(replay.EtfMarketBreadthMinute(
            trade_date=DAY.isoformat(), minute=minute, up=50, down=60, flat=70,
        ) for minute in intraday.MINUTES if minute not in ("09:30", "09:32"))

    calls = []
    fail = True

    async def request(operation, params, fields):
        calls.append((operation, params))
        if operation == "daily":
            return [dict(ts_code=symbol, trade_date="20261116", pre_close=10, vol=100) for symbol in SYMBOLS]
        symbol = params["ts_code"]
        if fail and symbol == SYMBOLS[-1]:
            raise TushareFailure("unavailable")
        assert operation == "stk_mins" and params["end_date"].endswith("09:32:00")
        prices = dict(zip(SYMBOLS, ([11, None, 8], [None, 8, None], [10, 12, 12]), strict=True))[symbol]
        return [dict(ts_code=symbol, trade_time=f"{DAY} {minute}:00", close=price, vol=1 if price else 0)
                for minute, price in zip(("09:30", "09:31", "09:32"), prices, strict=True)]

    monkeypatch.setattr(replay.tushare_market, "rows", request)
    worker = replay.BreadthReplay()
    monkeypatch.setattr(replay, "replay", worker)

    async def run():
        nonlocal fail
        assert await asyncio.gather(worker.start(DAY), worker.start(DAY)) == ["running", "running"]
        assert await worker.start(TODAY) == "busy"
        await worker.task
        assert (await worker.status(DAY))["processed"] == 2
        assert (await worker.status(DAY))["status"] == "partial"
        assert not market_stats._has_breadth(DAY, "09:30")
        fail = False
        # Simulate a restart: progress and already fetched bars come from SQLite.
        resumed = replay.BreadthReplay()
        assert (await resumed.status(DAY))["status"] == "partial"
        assert await resumed.start(DAY) == "running"
        await resumed.task
        assert (await resumed.status(DAY)) == {
            "status": "complete", "processed": 3, "total": 3, "added": 2, "through": "09:32", "reason": None,
        }
        assert await resumed.start(DAY) == "nothing_to_fill"

    asyncio.run(run())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/market-stats", params={"date": DAY.isoformat()})
        assert response.status_code == 200
        assert response.json()["backfill"]["added"] == 2
        points = response.json()["breadth"]["points"]
        assert points["09:30"] == {"up": 1, "down": 0, "flat": 1, "source": "backfill"}
        assert points["09:31"] == {"up": 50, "down": 60, "flat": 70}
        assert points["09:32"] == {"up": 1, "down": 2, "flat": 0, "source": "backfill"}
        assert client.post("/market-breadth/backfill", params={"date": DAY.isoformat()}).json()["status"] == "nothing_to_fill"
    assert [operation for operation, _ in calls] == ["daily", "stk_mins", "stk_mins", "stk_mins", "daily", "stk_mins"]
    assert calls[-1][1]["ts_code"] == SYMBOLS[-1]


def test_same_day_commits_complete_minutes_while_later_minute_is_still_pending(replay_storage, monkeypatch):
    monkeypatch.setattr(intraday, "now_cn", lambda: datetime(2026, 11, 17, 9, 33, 40, tzinfo=intraday.CN))
    monkeypatch.setattr(replay, "REQUESTS_PER_SECOND", 1000)
    monkeypatch.setattr(replay, "CONCURRENCY", 1)
    sh, sz, bj = SYMBOLS
    minutes = ("09:30", "09:31", "09:32", "09:33")
    with replay_storage.begin() as db:
        db.add(replay.EtfMarketBreadthMinute(trade_date=TODAY.isoformat(), minute="09:31", up=50, down=60, flat=70))
    replay._save_bars(TODAY, {
        sh: dict(zip(minutes, [11, None, 8, 8], strict=True)),
        sz: {"09:30": 8},
        bj: dict(zip(minutes[:3], [10, 12, None], strict=True)),
    })
    phase = 1
    requests = []

    async def run():
        nonlocal phase
        waiting_for_bj = asyncio.Event()
        release_bj = asyncio.Event()

        async def request(operation, params, fields):
            if operation == "rt_k":
                return [dict(ts_code=symbol, trade_time=f"{TODAY} 09:33:30", pre_close=10, vol=100)
                        for symbol in SYMBOLS]
            assert operation == "rt_min_daily"
            symbol = params["ts_code"]
            requests.append(symbol)
            if symbol == sz:
                values = [8, None, 9, 12]
            elif phase == 1:
                waiting_for_bj.set()
                await release_bj.wait()
                values = [10, 12]  # This shorter response may not erase cached 09:32.
            else:
                # 09:33 can be merged with the already-saved earlier minutes.
                return [dict(ts_code=bj, time=f"{TODAY} 09:33:00", close=12, vol=1)]
            return [dict(ts_code=symbol, time=f"{TODAY} {minute}:00", close=price, vol=int(price is not None))
                    for minute, price in zip(minutes, values)] + [
                # Latest-day upstream returns every available bar, even if the job was
                # launched with an earlier cutoff.
                dict(ts_code=symbol, time=f"{TODAY} 09:34:00", close=13, vol=1),
            ]

        monkeypatch.setattr(replay.tushare_market, "rows", request)
        worker = replay.BreadthReplay()
        assert await worker.start(TODAY) == "running"
        await asyncio.wait_for(waiting_for_bj.wait(), timeout=3)
        status = await worker.status(TODAY)
        assert status["status"] == "running" and status["added"] == 2 and status["through"] == "09:33"
        points = market_stats.read_session(TODAY, intraday.now_cn())["breadth"]["points"]
        assert points == {
            "09:30": {"up": 1, "down": 1, "flat": 1, "source": "backfill"},
            "09:31": {"up": 50, "down": 60, "flat": 70},
            "09:32": {"up": 1, "down": 2, "flat": 0, "source": "backfill"},
        }
        release_bj.set()
        await worker.task
        assert (await worker.status(TODAY))["status"] == "partial"
        bars = replay._cached_bars(TODAY)
        assert bars[bj]["09:32"] is None
        assert all("09:34" not in stock_bars for stock_bars in bars.values())

        phase = 2
        resumed = replay.BreadthReplay()
        assert await resumed.start(TODAY) == "running"
        await resumed.task
        assert (await resumed.status(TODAY))["status"] == "complete"
        assert market_stats.read_session(TODAY, intraday.now_cn())["breadth"]["points"]["09:33"] == {
            "up": 2, "down": 1, "flat": 0, "source": "backfill",
        }

    asyncio.run(run())
    assert requests == [sz, bj, bj]


def test_omitted_bar_does_not_look_like_known_no_trade():
    coverage = replay._MinuteCoverage({"600000.SH": 10}, {
        "600000.SH": {"09:30": 11, "09:32": None, "09:33": 8},
    }, ("09:30", "09:31", "09:32", "09:33"))
    assert coverage.ready() == {
        "09:30": {"up": 1, "down": 0, "flat": 0},
        "09:33": {"up": 0, "down": 1, "flat": 0},
    }


def test_manual_quota_pause_keeps_a_coverage_preview_and_retries_only_missing_stocks(replay_storage, monkeypatch):
    monkeypatch.setattr(intraday, "now_cn", lambda: datetime(2026, 11, 17, 9, 30, 40, tzinfo=intraday.CN))
    monkeypatch.setattr(replay, "REQUESTS_PER_SECOND", 1000)
    monkeypatch.setattr(replay, "CONCURRENCY", 1)
    monkeypatch.setattr(replay, "MIN_COOLDOWN_SECONDS", .01)
    monkeypatch.setattr(replay, "THROTTLED_INTERVAL_SECONDS", .004)
    sh, sz, bj = SYMBOLS
    replay._save_bars(TODAY, {sh: {"09:30": 11}})
    requested = []

    async def request(operation, params, fields):
        if operation == "rt_k":
            return [dict(ts_code=code, trade_time=f"{TODAY} 09:30:30", pre_close=10, vol=50) for code in SYMBOLS]
        code = params["ts_code"]
        requested.append(code)
        if code == bj and requested.count(bj) == 1:
            raise TushareFailure("rate_limited")
        return [dict(ts_code=code, time=f"{TODAY} 09:30:00", close=8, vol=50)]

    monkeypatch.setattr(replay.tushare_market, "rows", request)

    async def run():
        worker = replay.BreadthReplay()
        waiting, release = asyncio.Event(), asyncio.Event()
        original_wait = worker._wait_for_quota

        async def wait_for_quota(result):
            async def observe():
                await asyncio.sleep(0)
                waiting.set()
                await release.wait()
            await asyncio.gather(original_wait(result), observe())

        monkeypatch.setattr(worker, "_wait_for_quota", wait_for_quota)
        assert await worker.start(TODAY) == "running"
        await asyncio.wait_for(waiting.wait(), timeout=3)
        status = await worker.status(TODAY)
        assert status["status"] == "running" and status["reason"] == "rate_limited"
        assert await worker.preview_for(TODAY, status) == {
            "through": "09:30", "total": 3, "minimum": 0, "minutes": {"09:30": 2},
        }
        assert not market_stats._has_breadth(TODAY, "09:30")
        assert worker.pacer.interval >= .004
        release.set()
        await worker.task
        assert (await worker.status(TODAY))["status"] == "complete"
        assert market_stats._has_breadth(TODAY, "09:30")

    asyncio.run(run())
    assert requested == [sz, bj, bj]


def test_older_stopped_task_exposes_cached_sample_as_a_lower_bound():
    assert replay.coverage_preview({"status": "failed", "through": "11:30", "total": 5573, "processed": 240}) == {
        "through": "11:30", "total": 5573, "minimum": 240, "minutes": {},
    }


def test_request_pacer_limits_starts_to_four_per_second():
    async def run():
        pacer = replay._Pacer()
        starts = []

        async def request():
            await pacer.wait()
            starts.append(asyncio.get_running_loop().time())

        await asyncio.gather(*(request() for _ in range(5)))
        assert starts[4] - starts[0] >= 1.0

    asyncio.run(run())
