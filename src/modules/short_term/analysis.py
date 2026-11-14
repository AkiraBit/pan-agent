"""Deterministic observations, with explicit time and denominator gates."""
from datetime import datetime, time, timedelta, timezone
from statistics import mean, median

from marketdata.short_term import Batch, TZ
from src.platform.scheduling.trading_calendar import calendar_known, is_trading_day


PHASES = [(time(9, 15), "premarket"), (time(9, 20), "auction_early"),
          (time(9, 25), "auction_late"), (time(9, 30), "auction_result"),
          (time(10), "opening"), (time(11, 30), "trading"),
          (time(13), "break"), (time(15), "trading")]


def phase_at(now):
    now = now.astimezone(TZ)
    if not calendar_known("CN", now):
        return "unknown"
    if not is_trading_day("CN", now):
        return "closed"
    return next((phase for end, phase in PHASES if now.time() < end), "review")


def reference_day(now):
    day = now.astimezone(TZ).date()
    if now.astimezone(TZ).time() < time(9, 30):
        day -= timedelta(days=1)
    for _ in range(370):
        if is_trading_day("CN", day):
            return day.isoformat()
        day -= timedelta(days=1)
    return None


def breadth(rows):
    values = [r["change"] for r in rows if r.get("change") is not None]
    return {"valid": len(values), "rising": sum(v > 0 for v in values),
            "falling": sum(v < 0 for v in values), "flat": sum(v == 0 for v in values),
            "median": median(values) if values else None,
            "positive_ratio": sum(v > 0 for v in values) / len(values) if values else None}


def quality(batch: Batch, now, day):
    meta = batch.metadata()
    times = [r.get("source_time") for r in batch.rows]
    known = [t for t in times if t is not None]
    dated = [t for t in known if datetime.fromtimestamp(t, TZ).date().isoformat() == day]
    meta.update(source_time=min(known) if known else None, timed_count=len(known), freshness="unknown")
    if times and len(dated) == len(times):
        age = now.timestamp() - min(dated)
        future = max(dated) > now.timestamp() + 30
        meta["freshness"] = "stale" if future else ("fresh" if age <= 180 else "historical")
    elif known:
        meta["freshness"] = "stale"
    if meta["freshness"] == "stale":
        meta["status"] = "stale"
    return meta


def analyze(market, concepts, members, pools, now, day):
    phase = phase_at(now)
    mq = quality(market, now, day)
    stats = breadth(market.rows)
    # No live market verdict from yesterday's quotes, partial pages or auctions.
    usable = (mq["status"] == "complete" and mq["freshness"] == "fresh"
              and stats["valid"] >= (market.expected or 1) * 0.95
              and phase in {"opening", "trading"})
    ratio = stats["positive_ratio"]
    environment = ("broad_strength" if ratio >= .65 else "broad_weakness" if ratio <= .35 else "mixed") if usable else "pending"
    cq = quality(concepts, now, day)
    theme_rows = []
    up_codes = {r["code"] for r in pools["up"].rows} if pools["up"].status == "complete" else None
    universe_codes = {r["code"] for r in market.rows}
    for theme, batch in members:
        eligible = [r for r in batch.rows if r["code"] in universe_codes]
        b, q = breadth(eligible), quality(batch, now, day)
        enough = (usable and cq["status"] == "complete" and cq["freshness"] == "fresh" and q["status"] == "complete"
                  and q["freshness"] == "fresh" and b["valid"] >= max(3, len(eligible) * .95))
        strong = sum((r.get("change") or 0) >= 3 for r in eligible)
        synchronized = enough and b["positive_ratio"] >= .65 and b["median"] > 0 and strong >= 3
        theme_rows.append({"code": theme["code"], "name": theme["name"], "change": theme["change"],
                           "state": "synchronized" if synchronized else "divergent" if enough else "pending",
                           "breadth": b, "strong": strong, "quality": q,
                           "limit_up": sum(r["code"] in up_codes for r in eligible) if up_codes is not None else None,
                           "leaders": sorted([r for r in eligible if r["change"] is not None],
                                             key=lambda r: r["change"], reverse=True)[:3]})
    counts = {k: len(v.rows) if v.status == "complete" else None for k, v in pools.items()}
    values = [r["change"] for r in pools["yesterday"].rows if r["change"] is not None]
    yesterday = pools["yesterday"]
    yesterday_valid = yesterday.status == "complete" and len(values) == len(yesterday.rows)
    up, broken = counts["up"], counts["broken"]
    return {"version": 1, "captured_at": now.astimezone(timezone.utc).isoformat(), "trade_date": day, "phase": phase,
            "environment": environment, "market": {**stats, "quality": mq}, "themes": theme_rows,
            "concepts": cq, "sentiment": {"counts": counts,
                "yesterday_mean": mean(values) if values and yesterday_valid else None,
                "yesterday_valid": len(values), "yesterday_positive": sum(v > 0 for v in values) if yesterday_valid else None,
                "break_rate": broken / (up + broken) if up is not None and broken is not None and up + broken else None,
                "max_streak": max((r["streak"] or 0 for r in pools["up"].rows), default=0) if up is not None else None,
                "quality": {k: b.metadata() for k, b in pools.items()}},
            "auction": {"available": False, "reason": "no_verified_auction_feed"}}
