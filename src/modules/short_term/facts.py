"""Bounded live reads and immutable evidence for a premarket analysis run."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone

from marketdata.short_term import Batch, POOLS, TZ, quotes
from marketdata.sentiment import market_snapshot

from src.platform.marketdata.marketdata_client import get_market_data
from src.platform.scheduling.trading_calendar import calendar_known, is_trading_day
from .analysis import analyze, phase_at, reference_day
from .market_sources import limit_pool
from .speculation import candidate_concepts, relay_observation, theme_observation


class FactError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=TZ)).isoformat()
    return str(value)


def finite(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def symbol_for(code):
    code = str(code).split('.')[0]
    if len(code) != 6 or not code.isdigit() or code[0] not in "036":
        return None
    return code + (".SH" if code.startswith('6') else ".SZ")


def next_trade_date(now):
    local = now.astimezone(TZ)
    start = local.date() + timedelta(days=int(local.time() >= time(15)))
    for offset in range(32):
        day = start + timedelta(days=offset)
        if not calendar_known("CN", day):
            raise FactError("calendar_unknown")
        if is_trading_day("CN", day):
            return day.isoformat()
    raise FactError("calendar_unknown")


async def bounded_read(fn, *args, fallback=None, timeout=70, **kwargs):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout)
    except asyncio.CancelledError:
        raise
    except Exception:
        return fallback


def evidence(identity, kind, title, source, content, observed, *, published=None, url=None, status="observed"):
    body = json.dumps(content, ensure_ascii=False, sort_keys=True, default=iso, allow_nan=False)
    return {"id": identity, "kind": kind, "title": title, "source": source,
            "content": content, "observed_at": iso(observed), "published_at": iso(published),
            "url": url if url and str(url).startswith(('https://', 'http://')) else None,
            "status": status, "content_hash": hashlib.sha256(body.encode()).hexdigest()}


async def collect_facts(focus_symbols, memory_symbols=()):
    """Sources can degrade independently. No old snapshot is relabeled as a new read."""
    started = utc_now()
    day = reference_day(started)
    if not day or not calendar_known("CN", started):
        raise FactError("calendar_unknown")
    market, concepts, *pool_values = await asyncio.gather(
        bounded_read(quotes, fallback=Batch("market")),
        bounded_read(quotes, "concepts", "m:90+t:3", fallback=Batch("concepts")),
        *(bounded_read(limit_pool, kind, day, fallback=Batch(f"pool:{kind}"), timeout=15) for kind in POOLS),
    )
    pools = dict(zip(POOLS, pool_values))
    if market.status != 'complete':
        alternative = await bounded_read(market_snapshot, fallback=Batch('market'), timeout=70)
        if alternative.status == 'complete' or len(alternative.rows) > len(market.rows):
            market = alternative
    top = candidate_concepts(concepts)[:3]
    member_values = await asyncio.gather(*(bounded_read(quotes, f"theme:{r['code']}", f"b:{r['code']}",
                                                     fallback=Batch(f"theme:{r['code']}"), timeout=35) for r in top))
    members = list(zip(top, member_values))
    ranked = sorted(pools['up'].rows, key=lambda r: (r.get('streak') or 0, r.get('amount') or 0), reverse=True)
    ranked += sorted(pools['yesterday'].rows, key=lambda r: r.get('previous_streak') or 0, reverse=True)[:8]
    ranked += sorted(market.rows, key=lambda r: r.get('amount') or 0, reverse=True)[:8]
    selected = list(dict.fromkeys([*focus_symbols, *memory_symbols,
                                  *(s for r in ranked if (s := symbol_for(r['code'])))]))[:24]
    if not selected:
        raise FactError("market_data_unavailable")
    md = get_market_data()
    codes = [s.split('.')[0] for s in selected]
    quote_values, news = await asyncio.gather(
        bounded_read(md.quotes, codes, market="CN", fallback=[], timeout=30),
        bounded_read(md.news, codes[:6], market="CN", since_hours=96, now=started.astimezone(TZ), fallback=[], timeout=35),
    )
    observed = utc_now()
    market_by_code = {r['code']: r for r in market.rows}
    live = {q.symbol.split('.')[0]: q for q in quote_values}
    rows = []
    ev = []
    for symbol in selected:
        code = symbol.split('.')[0]
        q = live.get(code)
        r = market_by_code.get(code, {})
        stamp = iso(q.source_timestamp) if q else (datetime.fromtimestamp(r['source_time'], TZ).isoformat() if r.get('source_time') else None)
        quote_day = iso(q.quote_date) if q else (datetime.fromisoformat(stamp).date().isoformat() if stamp else None)
        valid_date = quote_day == day and (not stamp or datetime.fromisoformat(stamp) <= observed + timedelta(seconds=30))
        price = finite(q.current_price if q else r.get('price'))
        row = {"symbol": symbol, "name": (q.name if q else r.get('name')) or code,
               "price": price, "change_pct": finite(q.change_pct if q else r.get('change')),
               "amount_cny": finite(q.turnover if q else r.get('amount')),
               "source": (q.source if q else market.provider) or "unknown",
               "source_time": stamp, "trade_date": quote_day, "observed_at": iso(observed),
               "quality": "available" if valid_date and price and price > 0 else "stale" if price else "unavailable"}
        rows.append(row)
        ev.append(evidence(f"quote:{code}", "quote", f"{row['name']} / {quote_day or 'unknown'}", row['source'],
                           row, observed, published=stamp, status=row['quality']))
    if not any(r['quality'] == 'available' for r in rows):
        raise FactError("market_data_stale")
    snapshot = analyze(market, concepts, members, pools, observed.astimezone(TZ), day)
    snapshot['speculation'] = {"relay": relay_observation(pools), "themes": theme_observation(market, concepts, members, pools)}
    ev.insert(0, evidence("market:breadth", "market", "Shanghai / Shenzhen market breadth", market.provider,
                          snapshot['market'], observed, status=market.status))
    for kind, batch in pools.items():
        ev.append(evidence(f"pool:{kind}", "pool", f"{day} / {kind}", batch.provider,
                           {"quality": batch.metadata(), "rows": batch.rows[:24], "sample_limit": 24,
                            "total_rows": len(batch.rows)}, observed, status=batch.status))
    for theme, batch in members:
        ev.append(evidence(f"theme:{theme['code']}", "theme", theme['name'], "eastmoney",
                           {"quality": batch.metadata(), "members": [r['code'] for r in batch.rows[:24]],
                            "sample_limit": 24, "total_rows": len(batch.rows)}, observed, status=batch.status))
    for article in news[:20]:
        published = article.publish_time
        if not isinstance(published, datetime):
            continue
        published = published if published.tzinfo else published.replace(tzinfo=TZ)
        if published > observed or published < observed - timedelta(days=7):
            continue
        key = hashlib.sha256((article.source + str(article.external_id)).encode()).hexdigest()[:16]
        ev.append(evidence(f"news:{key}", "news", article.title[:300], article.source,
                           {"text": (article.content or '')[:3000], "symbols": article.symbols}, observed,
                           published=published, url=article.url, status="reported"))
    ev.append(evidence("capability:constraints", "capability", "Constraint verification coverage", "panwatch",
                       {"auction": False, "regulatory_monitoring": "unverified", "abnormal_window": "not_calculated",
                        "news_symbols": codes[:6], "news_items": len([e for e in ev if e['kind'] == 'news'])}, observed))
    raw = {"market": asdict(market), "concepts": asdict(concepts), "pools": {k: asdict(v) for k, v in pools.items()},
           "members": {r['code']: asdict(batch) for r, batch in members}}
    return {"schema_version": "1.0", "collected_at": iso(observed), "started_at": iso(started),
            "reference_trade_date": day, "phase": phase_at(observed), "scope": "CN_SH_SZ",
            "coverage": market.metadata(), "snapshot": snapshot, "quotes": rows, "evidence": ev,
            "capabilities": {"auction": False, "abnormal_window": False, "regulatory_monitoring": False,
                             "continuous_monitoring": False}, "raw": raw}


def model_facts(facts):
    """The raw archive is immutable but need not consume the model context budget."""
    # Evidence is bounded before hashing; the displayed body always matches its hash.
    return {k: v for k, v in facts.items() if k != 'raw'}
