"""Separate speculative participation, relay cohorts and completed-bar trends.

These are source-scoped observations, not leader designations or buy signals.
Industry labels from the limit pool are deliberately not used as themes.
"""
from collections import defaultdict
from datetime import date
from statistics import mean

from marketdata.short_term import number


def positive_integer(value):
    n = number(value)
    return int(n) if n is not None and n >= 1 and n.is_integer() else None


def candidate_concepts(concepts):
    # Eastmoney's concept directory also contains index, ownership, valuation,
    # size and technical screens. Those are not event/industry narratives.
    # Keep policy themes such as 大基金持股 and 央国企改革 deliberately.
    broad = ("融资融券", "沪股通", "深股通", "富时", "MSCI", "标普", "标准普尔",
             "中证", "上证", "深证", "深成", "HS300", "央视50", "创业板综", "创业成份",
             "重仓", "新进", "基金增仓", "基金减仓", "养老金", "证金持股", "券商金股",
             "大盘", "中盘", "小盘", "微盘", "风格", "市盈率", "市净率", "高成长股",
             "连续亏损", "题材股", "反转股", "趋势股", "密集调研", "股权分散", "股权集中",
             "新高", "破增发价", "破发股", "超跌股", "微利股", "红利股", "价值股", "周期股",
             "权重股", "行业龙头", "东方财富热股", "最近多板", "破净", "百元股", "低价股",
             "宁组合", "茅指数", "转债标的", "ST股", "AH股", "AB股", "B股", "GDR", "昨日",
             "预增", "预减", "扭亏", "首亏")
    rows = [r for r in concepts.rows if r.get("change") is not None
            and not any(word in r["name"] for word in broad)]
    chosen = {}
    for field in ("change", "amount"):
        for row in sorted(rows, key=lambda r: r.get(field) or 0, reverse=True)[:6]:
            chosen[row["code"]] = row
    return list(chosen.values())


def relay_observation(pools):
    up, previous = pools["up"], pools["yesterday"]
    up_ok, previous_ok = up.status == "complete", previous.status == "complete"
    up_by_code = {r["code"]: r for r in up.rows}
    broken = {r["code"] for r in pools["broken"].rows}
    down = {r["code"] for r in pools["down"].rows}
    ladder, cohorts, feedback = defaultdict(list), defaultdict(list), []
    for row in up.rows:
        level = positive_integer(row.get("streak"))
        if level:
            ladder[level].append(row)
    for row in previous.rows:
        level = positive_integer(row.get("previous_streak"))
        if not level:
            continue
        current = up_by_code.get(row["code"])
        current_level = positive_integer(current.get("streak")) if current else None
        state = "unknown"
        if up_ok and previous_ok:
            if current and ((row["code"] in down and pools["down"].status == "complete") or (row["code"] in broken and pools["broken"].status == "complete")):
                state = "conflict"
            elif current:
                state = "promoted" if current_level == level + 1 else "conflict"
            elif row["code"] in down and pools["down"].status == "complete":
                state = "limit_down"
            elif row["code"] in broken and pools["broken"].status == "complete":
                state = "broken"
            elif row.get("change") is not None:
                state = "not_sealed"
        item = {**row, "previous_streak": level, "state": state}
        cohorts[level].append(item)
        feedback.append(item)
    levels = []
    for level, rows in sorted(cohorts.items()):
        known = up_ok and previous_ok and all(r["state"] not in {"unknown", "conflict"} for r in rows)
        promoted = sum(r["state"] == "promoted" for r in rows) if known else None
        levels.append({"level": level, "total": len(rows), "promoted": promoted,
                       "rate": promoted / len(rows) if promoted is not None else None})
    highest_previous = max(cohorts, default=None) if previous_ok and len(feedback) == len(previous.rows) else None
    anchors = [r for r in feedback if r["previous_streak"] == highest_previous]
    return {"complete": up_ok and previous_ok, "height": max(ladder, default=None) if up_ok and sum(map(len, ladder.values())) == len(up.rows) else None,
            "previous_height": highest_previous,
            "ungraded_up": len(up.rows) - sum(map(len, ladder.values())),
            "ungraded_previous": len(previous.rows) - len(feedback),
            "ladder": [{"level": n, "count": len(rows), "stocks": sorted(rows, key=lambda r: r.get("first_time") or "99:99:99")}
                       for n, rows in sorted(ladder.items(), reverse=True)],
            "promotion": levels, "anchors": anchors,
            "negative_feedback": sorted([r for r in feedback if r.get("change") is not None and r["change"] < 0],
                                        key=lambda r: r["change"])[:8]}


def theme_observation(market, concepts, members, pools):
    universe = {r["code"] for r in market.rows}
    up = {r["code"]: r for r in pools["up"].rows}
    previous = {r["code"]: r for r in pools["yesterday"].rows}
    rows = []
    for theme, batch in members:
        codes = {r["code"] for r in batch.rows} & universe
        sealed = [r for code, r in up.items() if code in codes]
        known = market.status == pools["up"].status == batch.status == "complete"
        graded = [r for r in sealed if positive_integer(r.get("streak"))]
        primary = sorted(graded, key=lambda r: (-(r["streak"]), r.get("first_time") or "99:99:99"))
        old = [r for code, r in previous.items() if code in codes]
        known_old = pools["yesterday"].status == "complete" and old and all(r.get("change") is not None for r in old)
        rows.append({"code": theme["code"], "name": theme["name"], "change": theme["change"],
                     "member_count": len(codes), "complete": known, "limit_up": len(sealed) if known else None,
                     "first_boards": sum(r["streak"] == 1 for r in graded) if known and len(graded) == len(sealed) else None,
                     "relay_boards": sum(r["streak"] >= 2 for r in graded) if known and len(graded) == len(sealed) else None,
                     "height": max((r["streak"] for r in graded), default=None) if known and len(graded) == len(sealed) else None,
                     "previous_mean": mean(r["change"] for r in old) if known_old else None,
                     "core": primary[:4], "overlaps": [], "catalyst_verified": False, "_codes": codes})
    rows.sort(key=lambda r: (r["complete"], r["limit_up"] or 0, r["relay_boards"] or 0, r["height"] or 0), reverse=True)
    distinct = []
    for item in rows:
        # Display one representative when Jaccard overlap is very high; no causal/story merge.
        overlap = next((r for r in distinct if item["_codes"] and
                        len(item["_codes"] & r["_codes"]) / len(item["_codes"] | r["_codes"]) >= .8), None)
        if overlap:
            overlap["overlaps"].append(item["name"])
        else:
            distinct.append(item)
    for item in distinct:
        item.pop("_codes")
    return {"scanned": len(members), "available": concepts.expected, "candidates": distinct[:6]}


def trend_candidates(market, members):
    affiliations = defaultdict(list)
    for theme, batch in members:
        if batch.status == "complete":
            for r in batch.rows:
                affiliations[r["code"]].append(theme["name"])
    eligible = [r for r in market.rows if r["code"] in affiliations and (r.get("amount") or 0) > 0]
    return [{**r, "themes": affiliations[r["code"]]} for r in sorted(eligible, key=lambda r: r["amount"], reverse=True)[:6]]


def trend_structure(bars, completed_day):
    valid = []
    for b in bars:
        try:
            day = date.fromisoformat(str(b["date"]))
        except (ValueError, KeyError):
            return {"state": "invalid"}
        if day.isoformat() <= completed_day:
            valid.append(b)
    valid.sort(key=lambda b: b["date"])
    valid = valid[-25:]
    if len(valid) < 25:
        return {"state": "insufficient", "bars": len(valid)}
    if len({b["date"] for b in valid}) != len(valid):
        return {"state": "invalid"}
    prices = [(number(b.get("close")), number(b.get("high"))) for b in valid]
    if any(close is None or high is None or close <= 0 or high < close for close, high in prices):
        return {"state": "invalid"}
    closes = [close for close, _ in prices]
    ma5, ma10, ma20 = (mean(closes[-n:]) for n in (5, 10, 20))
    rising = ma20 > mean(closes[-25:-5])
    state = "aligned" if closes[-1] > ma5 > ma10 > ma20 and rising else "above" if closes[-1] >= ma20 else "below"
    return {"state": state if valid[-1]["date"] == completed_day else "stale", "as_of": valid[-1]["date"],
            "distance_ma20": (closes[-1] / ma20 - 1) * 100,
            "ma20_change": (ma20 / mean(closes[-25:-5]) - 1) * 100,
            "drawdown20": (closes[-1] / max(high for _, high in prices[-20:]) - 1) * 100,
            "return5": (closes[-1] / closes[-6] - 1) * 100}
