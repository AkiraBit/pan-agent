"""Resolve configured candidates, then return the first compatible usable result."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import time

from marketdata.cache import TTLCache
from marketdata.fallback import Cooldown, InvalidRequest, NoData
from marketdata.http import attempt_budget, record_error
from marketdata.ports import ConfigProvider, MetricsSink
from marketdata.symbol import Market, Symbol
from marketdata.types import Quote, Request, Response
from marketdata.vendors.base import Vendor

logger = logging.getLogger(__name__)


def _cache_key(req, datatype, sources):
    fingerprint = [(s.vendor, s.priority, s.config) for s in sources]
    digest = hashlib.sha256(json.dumps(fingerprint, default=str, sort_keys=True).encode()).hexdigest()
    return req.cache_key(datatype) + "|" + digest


def _quality(data, req):
    rows = [row for row in data if all(
        (row.get(name) if isinstance(row, dict) else getattr(row, name, None)) is not None
        for name in req.required_fields)]
    rows = [row for row in rows if not isinstance(row, Quote) or (
        type(row.current_price) in (float, int) and math.isfinite(row.current_price) and row.current_price > 0)]
    if req.trade_date:
        rows = [row for row in rows if getattr(row, "quote_date", None) == req.trade_date]
    if req.max_age_seconds is None:
        return rows
    now = datetime.now(timezone.utc)
    return [row for row in rows if (
        isinstance(at := getattr(row, "source_timestamp", None), datetime)
        and at.tzinfo is not None and -5 <= (now - at).total_seconds() <= req.max_age_seconds
    ) or (at is None and req.trade_date is not None)]


class Engine:
    def __init__(self, *, datatype: str, vendors: dict[str, Vendor],
                 config: ConfigProvider, metrics: MetricsSink,
                 cache: TTLCache, default_ttl: float):
        self.datatype = datatype
        self.vendors = vendors
        self.config = config
        self.metrics = metrics
        self.cache = cache
        self.default_ttl = default_ttl
        self.cooldown = Cooldown()
        self.last_good = TTLCache()

    def fetch(self, req: Request, *, cache_ttl_sec: float | None = None, min_count: int = 1) -> Response:
        if req.limit < 1 or min_count < 1:
            return Response(ok=False, error="invalid request limits")
        market = req.market
        symbols = [Symbol(Market(market), code) for code in dict.fromkeys(req.symbols)]
        sources = [src for src in sorted(self.config.sources_for(self.datatype, market), key=lambda s: s.priority)
                   if src.enabled and (vendor := self.vendors.get(src.vendor)) is not None
                   and (not vendor.supports_markets or market in vendor.supports_markets)]
        if not sources:
            return Response(ok=False, error="no enabled provider")
        key = _cache_key(req, self.datatype, sources) + f"|{min_count}"
        ttl = cache_ttl_sec if cache_ttl_sec is not None else self.default_ttl
        deadline = time.monotonic() + req.timeout_budget_seconds
        cached = self.cache.get(key)
        if cached is not None and (req.max_age_seconds is None or len(_quality(cached.data, req)) == len(cached.data)):
            return cached

        def save(response):
            # A successful backup shouldn't mask a recovered primary for a long TTL.
            self.cache.set(key, response, ttl_sec=ttl if response.vendor == sources[0].vendor else min(ttl, 5))
            if req.stale_if_error_seconds and len(response.data) >= min_count:
                self.last_good.set(key, response, ttl_sec=max(ttl, 0) + req.stale_if_error_seconds)
            return response

        last_error = ""
        best = None
        quote_by_symbol: dict[str, tuple[Quote, str]] = {}
        for src in sources:
            seconds_left = deadline - time.monotonic()
            if seconds_left <= 0:
                last_error = "timeout budget exhausted"
                break
            step = (src.vendor, market)
            if not self.cooldown.available(step):
                last_error = "provider cooling down"
                continue
            pending = [sym for sym in symbols if sym.code not in quote_by_symbol]
            t0 = time.monotonic()

            def measure(ok, *, count=0, error=""):
                self.metrics.record(vendor=src.vendor, datatype=self.datatype, market=market,
                                    ok=ok, count=count, latency_ms=int((time.monotonic() - t0) * 1000), error=error)

            try:
                allowance = min(6, seconds_left) if len(sources) > 1 else seconds_left
                call_config = {**(src.config or {}), "days": req.limit, **dict(req.extra), "_timeout": allowance}
                with attempt_budget(allowance):
                    data = _quality(self.vendors[src.vendor].fetch(pending, call_config) or [], req)
            except InvalidRequest as exc:
                return Response(ok=False, error=str(exc))
            except NoData:
                self.cooldown.succeeded(step)
                measure(True)
                if not quote_by_symbol:
                    return save(Response(ok=True, data=[], vendor=src.vendor))
                break
            except Exception as exc:
                last_error = str(exc)
                self.cooldown.failed(step, getattr(exc, "retry_after", 0))
                measure(False, error=last_error)
                logger.debug("[marketdata/%s] vendor=%s failed: %s", self.datatype, src.vendor, type(exc).__name__)
                record_error(f"{src.vendor}: {type(exc).__name__}: {exc}")
                continue

            if not data:
                last_error = "empty or quality requirements not met"
                measure(False, error=last_error)
                continue
            self.cooldown.succeeded(step)
            measure(True, count=len(data))
            if self.datatype == "quote" and symbols and all(isinstance(row, Quote) for row in data):
                wanted = {sym.code for sym in pending}
                for row in data:
                    if row.symbol in wanted and row.market == market and row.symbol not in quote_by_symbol:
                        quote_by_symbol[row.symbol] = (row if row.source else replace(row, source=src.vendor), src.vendor)
                if len(quote_by_symbol) == len(symbols):
                    return save(self._quote_result(symbols, quote_by_symbol))
                continue
            response = Response(ok=True, data=data, vendor=src.vendor, latency_ms=int((time.monotonic() - t0) * 1000))
            if len(data) >= min_count:
                return save(response)
            if best is None or len(data) > len(best.data):
                best = response

        if quote_by_symbol:
            return save(self._quote_result(symbols, quote_by_symbol))
        if best is not None:
            return save(replace(best, partial=True))
        stale = self.last_good.get(key) if req.stale_if_error_seconds else None
        if stale is not None:
            return replace(stale, stale=True)
        return Response(ok=False, data=None, error=last_error or "no usable provider")

    @staticmethod
    def _quote_result(symbols, quotes):
        rows = [quotes[sym.code][0] for sym in symbols if sym.code in quotes]
        vendors = tuple(dict.fromkeys(vendor for _, vendor in quotes.values()))
        return Response(ok=True, data=rows, vendor=vendors[0] if len(vendors) == 1 else "mixed",
                        sources=vendors, partial=len(rows) < len(symbols))
