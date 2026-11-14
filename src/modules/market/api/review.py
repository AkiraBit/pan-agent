"""Authenticated, allow-listed read-only market review endpoints."""
from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, HTTPException, Path

from src.modules.market.review_data import ReviewUnavailable, load_review

router = APIRouter()


@router.get("/{resource}")
async def review_resource(resource: Literal["board", "dates", "overseas", "daily", "etf"], date: Date | None = None):
    if date and resource != "board":
        raise HTTPException(422, "Only the limit-up board supports a trading date")
    try:
        return await load_review(resource, date.isoformat() if date else None)
    except ReviewUnavailable:
        raise HTTPException(503, "行情来源暂时不可用，请稍后重试") from None


@router.get("/minute/{code}")
async def review_minute(date: Date, code: str = Path(pattern=r"^\d{6}$")):
    try:
        return await load_review(f"minute/{code}", date.isoformat())
    except ReviewUnavailable:
        raise HTTPException(503, "该交易日分时数据暂不可用") from None
