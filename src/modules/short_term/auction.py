"""Read the configured Tonghuashun auction data source."""
from __future__ import annotations

from datetime import datetime, time

from pydantic import Field

from marketdata.short_term import TZ
from src.platform.marketdata import fuyao_business
from .schemas import Contract, Symbol


class AuctionQuote(Contract):
    symbol: Symbol
    source_time: datetime
    reference_price: float = Field(gt=0)
    pre_close: float = Field(gt=0)
    matched_volume_shares: float = Field(ge=0)
    unmatched_volume_shares: float = Field(ge=0)
    unmatched_side: str = Field(pattern='^(balanced|unknown)$')
    final: bool = False


async def read_auction(symbols, now):
    import asyncio

    output = {"provider": "fuyao", "observed_at": now.isoformat(), "quotes": [], "errors": []}
    if not time(9, 15) <= now.astimezone(TZ).time() < time(9, 30):
        return {**output, "status": "outside_auction"}
    if "fuyao" not in await asyncio.to_thread(fuyao_business.providers, "auction"):
        return {**output, "status": "not_configured"}
    return await _read_fuyao(symbols, now)


async def _read_fuyao(symbols, now):
    output = {'status': 'unavailable', 'provider': 'fuyao', 'observed_at': now.isoformat(), 'quotes': [], 'errors': []}
    if not symbols:
        return output
    local = now.astimezone(TZ)
    final = local.time() >= time(9, 25)
    stage = "final" if final else "live"
    try:
        data = await fuyao_business.fetch("get_a_share_auction_snapshot", {
            "thscodes": ",".join(dict.fromkeys(symbols)), "stage": stage,
        })
        if not data or data.get("auction_phase") != stage or data.get("data_status") != "ready":
            return output
        stamp = datetime.fromtimestamp(data["timestamp"] / 1000, TZ)
        age = (now - stamp).total_seconds()
        if stamp.date() != local.date() or not 0 <= age <= (300 if final else 15):
            return output
        if not (time(9, 25) <= stamp.time() < time(9, 30) if final else time(9, 15) <= stamp.time() < time(9, 25)):
            return output
        seen = set()
        for row in data["item"]:
            symbol = row.get("thscode")
            if symbol not in symbols or symbol in seen:
                continue
            seen.add(symbol)
            try:
                qty = float(row["auction_unmatched"])
                q = AuctionQuote(symbol=symbol, source_time=stamp, reference_price=row["auction_price"],
                    pre_close=row["pre_close_price"], matched_volume_shares=row["auction_volume"],
                    unmatched_volume_shares=abs(qty), unmatched_side="balanced" if qty == 0 else "unknown", final=final)
            except (ValueError, TypeError, KeyError):
                output["errors"].append({"symbol": symbol, "reason": "invalid_auction_row"})
                continue
            # The upstream schema gives unmatched volume but does not specify direction.
            item = q.model_dump(mode="json")
            item.update(auction_change_pct=(q.reference_price / q.pre_close - 1) * 100,
                        matched_amount_cny=q.reference_price * q.matched_volume_shares,
                        unmatched_ratio=0 if qty == 0 and q.matched_volume_shares else None)
            output["quotes"].append(item)
        output["status"] = "available" if len(seen) == len(output["quotes"]) == len(set(symbols)) else (
            "partial" if output["quotes"] else "unavailable")
    except (RuntimeError, ValueError, TypeError, KeyError, OSError, OverflowError):
        output["status"] = "source_error"
    return output
