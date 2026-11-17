from marketdata.cache import TTLCache
from marketdata.defaults import InMemoryMetricsSink
from marketdata.engine import Engine
from marketdata.ports import SourceConfig
from marketdata.types import Request


class FakeVendor:
    def __init__(self, name, behavior):
        self.name, self.behavior, self.supports_markets = name, behavior, set()

    def fetch(self, symbols, config):
        if self.behavior == "raise":
            raise RuntimeError("boom")
        if self.behavior == "empty":
            return []
        return [{"symbol": symbols[0].code, "v": self.name}]


class FakeConfig:
    def __init__(self, srcs):
        self._srcs = srcs

    def sources_for(self, datatype, market):
        return list(self._srcs)


def _engine(vendors, srcs, metrics=None):
    return Engine(
        datatype="quote", vendors=vendors, config=FakeConfig(srcs),
        metrics=metrics or InMemoryMetricsSink(), cache=TTLCache(5.0), default_ttl=5.0,
    )


def _req():
    return Request(symbols=("600519",), market="CN")


def test_first_success_wins():
    e = _engine({"a": FakeVendor("a", "ok"), "b": FakeVendor("b", "ok")},
                [SourceConfig(vendor="a", priority=1), SourceConfig(vendor="b", priority=2)])
    r = e.fetch(_req())
    assert r.ok and r.vendor == "a" and r.data[0]["v"] == "a"


def test_failover_empty_then_raise_then_ok():
    e = _engine({"a": FakeVendor("a", "empty"), "b": FakeVendor("b", "raise"), "c": FakeVendor("c", "ok")},
                [SourceConfig(vendor="a", priority=1), SourceConfig(vendor="b", priority=2), SourceConfig(vendor="c", priority=3)])
    r = e.fetch(_req())
    assert r.ok and r.vendor == "c"


def test_all_fail_returns_not_ok():
    e = _engine({"a": FakeVendor("a", "empty")}, [SourceConfig(vendor="a", priority=1)])
    assert e.fetch(_req()).ok is False


def test_market_filter_skips_unsupported():
    v = FakeVendor("a", "ok")
    v.supports_markets = {"US"}   # 不支持 CN
    assert _engine({"a": v}, [SourceConfig(vendor="a", priority=1)]).fetch(_req()).ok is False


def test_cache_hit_skips_second_call():
    v = FakeVendor("a", "ok")
    calls = {"n": 0}
    inner = v.fetch
    v.fetch = lambda s, c: (calls.__setitem__("n", calls["n"] + 1), inner(s, c))[1]
    e = _engine({"a": v}, [SourceConfig(vendor="a", priority=1)])
    e.fetch(_req()); e.fetch(_req())
    assert calls["n"] == 1


def test_metrics_recorded():
    m = InMemoryMetricsSink()
    _engine({"a": FakeVendor("a", "ok")}, [SourceConfig(vendor="a", priority=1)], metrics=m).fetch(_req())
    assert m.snapshot()["a"]["success_rate"] == 1.0


def test_priority_resort_when_config_unsorted():
    e = _engine({"a": FakeVendor("a", "ok"), "b": FakeVendor("b", "ok")},
                [SourceConfig(vendor="b", priority=2), SourceConfig(vendor="a", priority=1)])
    r = e.fetch(_req())
    assert r.ok and r.vendor == "a"


def test_min_count_prefers_first_sufficient():
    e = _engine({"a": FakeVendor("a", "ok"), "b": FakeVendor("b", "ok")},
                [SourceConfig(vendor="a", priority=1), SourceConfig(vendor="b", priority=2)])
    # FakeVendor "ok" 返回 1 条;min_count=2 → a 不足 → 试 b → b 也 1 条 → 都不足 → 取最长(并列取先到的 a)
    r = e.fetch(Request(symbols=("600519",), market="CN"), min_count=2)
    assert r.ok and len(r.data) == 1  # 返回了(最长的),不因不足而失败


def test_min_count_returns_first_meeting_threshold():
    class MultiVendor:
        def __init__(self, name, n): self.name=name; self.supports_markets=set(); self._n=n
        def fetch(self, symbols, config): return [{"i": i} for i in range(self._n)]
    e = _engine({"a": MultiVendor("a", 1), "b": MultiVendor("b", 5)},
                [SourceConfig(vendor="a", priority=1), SourceConfig(vendor="b", priority=2)])
    r = e.fetch(Request(symbols=("x",), market="CN"), min_count=3)
    assert r.ok and r.vendor == "b" and len(r.data) == 5  # a 不足(1<3)→ b 足(5≥3)


def test_min_count_default_one_unchanged():
    e = _engine({"a": FakeVendor("a", "ok")}, [SourceConfig(vendor="a", priority=1)])
    r = e.fetch(Request(symbols=("x",), market="CN"))  # 默认 min_count=1
    assert r.ok and r.vendor == "a"


def test_engine_passes_request_limit_as_days_to_vendor():
    seen = {}
    class DaysVendor:
        name = "d"
        supports_markets: set = set()
        def fetch(self, symbols, config):
            seen["days"] = config.get("days")
            return [{"x": 1}]
    e = _engine({"d": DaysVendor()}, [SourceConfig(vendor="d", priority=1)])
    e.fetch(Request(symbols=("x",), market="CN", limit=250))
    assert seen["days"] == 250


def test_engine_passes_request_extra_to_vendor_config():
    # 守护测试:events 等 vendor 需要 req.extra(如 since_days)透传进 call_config。
    seen = {}
    class ExtraVendor:
        name = "e"
        supports_markets: set = set()
        def fetch(self, symbols, config):
            seen["since_days"] = config.get("since_days")
            seen["days"] = config.get("days")
            return [{"x": 1}]
    e = _engine({"e": ExtraVendor()}, [SourceConfig(vendor="e", priority=1)])
    e.fetch(Request(symbols=("x",), market="CN", limit=99, extra=(("since_days", 30),)))
    assert seen["since_days"] == 30
    assert seen["days"] == 99  # extra 透传不应破坏原有 days 注入


def test_batch_fill_retains_primary_values_and_queries_only_missing_symbols():
    from marketdata.types import Quote

    calls = []
    def vendor(name, price, covers):
        item = FakeVendor(name, "ok")
        def fetch(symbols, config):
            calls.append((name, [s.code for s in symbols]))
            return [Quote(s.code, "CN", price) for s in symbols if s.code in covers]
        item.fetch = fetch
        return item

    engine = _engine({"a": vendor("a", 12, {"600519"}), "b": vendor("b", 4, {"600519", "000001"})},
                     [SourceConfig("a", 0), SourceConfig("b", 1)])
    result = engine.fetch(Request(("600519", "000001")), min_count=2)
    assert calls == [("a", ["600519", "000001"]), ("b", ["000001"])]
    assert result.sources == ("a", "b") and not result.partial
    assert [(q.current_price, q.source) for q in result.data] == [(12, "a"), (4, "b")]


def test_rate_limit_temporarily_skips_primary_and_then_restores_it():
    from marketdata.fallback import SourceFailure

    now, calls = [10.0], []
    primary = FakeVendor("a", "ok")
    def fetch(symbols, config):
        calls.append("a")
        if now[0] < 50:
            raise SourceFailure("rate limited", retry_after=40)
        return [{"symbol": symbols[0].code}]
    primary.fetch = fetch
    engine = _engine({"a": primary, "b": FakeVendor("b", "ok")}, [SourceConfig("a", 0), SourceConfig("b", 1)])
    engine.cooldown.clock = lambda: now[0]
    assert engine.fetch(_req(), cache_ttl_sec=0).vendor == "b"
    now[0] = 49
    assert engine.fetch(_req(), cache_ttl_sec=0).vendor == "b"
    assert calls == ["a"]
    now[0] = 50
    assert engine.fetch(_req(), cache_ttl_sec=0).vendor == "a"
    assert calls == ["a", "a"]


def test_stale_snapshot_is_labeled_and_never_used_after_disable():
    from datetime import datetime, timedelta, timezone
    from marketdata.types import Quote

    fresh = datetime.now(timezone.utc)
    main = FakeVendor("a", "ok")
    alternate = FakeVendor("b", "ok")
    main.fetch = lambda symbols, config: [Quote("600519", "CN", 7, source_timestamp=fresh - timedelta(hours=1))]
    alternate.fetch = lambda symbols, config: [Quote("600519", "CN", 8, source_timestamp=fresh)]
    srcs = [SourceConfig("a", 0), SourceConfig("b", 1)]
    engine = _engine({"a": main, "b": alternate}, srcs)
    request = Request(("600519",), max_age_seconds=30, stale_if_error_seconds=120)
    assert engine.fetch(request, cache_ttl_sec=0).vendor == "b"
    alternate.fetch = lambda symbols, config: []
    stale = engine.fetch(request, cache_ttl_sec=0)
    assert stale.stale and stale.data[0].current_price == 8
    srcs[1].enabled = False
    assert not engine.fetch(request, cache_ttl_sec=0).ok


def test_invalid_request_and_authoritative_empty_do_not_call_backups():
    from marketdata.fallback import InvalidRequest, NoData

    attempts = []
    a, b = FakeVendor("a", "ok"), FakeVendor("b", "ok")
    b.fetch = lambda symbols, config: attempts.append("b")
    engine = _engine({"a": a, "b": b}, [SourceConfig("a", 0), SourceConfig("b", 1)])

    def raises(exc):
        def fetch(symbols, config): raise exc
        return fetch

    a.fetch = raises(InvalidRequest("bad period"))
    assert not engine.fetch(_req(), cache_ttl_sec=0).ok
    a.fetch = raises(NoData())
    result = engine.fetch(_req(), cache_ttl_sec=0)
    assert result.ok and result.data == [] and not attempts
