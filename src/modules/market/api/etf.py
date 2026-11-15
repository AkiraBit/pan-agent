"""Authenticated ETF read API, including versioned observations for analysis agents."""
import asyncio
from datetime import date as Date, datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from src.platform.persistence.database import SessionLocal
from src.modules.market.etf import service, sources
from src.modules.market.etf.models import EtfSnapshot

router = APIRouter()


def validate_date(value):
    if value and value.isoformat() > sources.today():
        raise HTTPException(422, '交易日不能晚于今天')
    return value.isoformat() if value else None


async def load(date=None):
    requested = validate_date(date)
    try:
        return await service.board(requested)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        raise HTTPException(503, '该交易日 ETF 行情暂不可用') from None


@router.get('/board')
async def board(date: Date | None = None):
    return await load(date)


@router.get('/dates')
async def dates():
    try:
        return await service.dates()
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(503, 'ETF 交易日暂不可用') from None


@router.get('/national-team')
async def national_team(date: Date | None = None, known_at: datetime | None = None):
    if known_at and known_at.tzinfo is None:
        raise HTTPException(422, 'known_at 必须包含时区')
    cutoff = known_at.astimezone(timezone.utc).isoformat() if known_at else None
    if cutoff:
        result = await asyncio.to_thread(service.saved_board, validate_date(date), cutoff)
        if result is None:
            raise HTTPException(404, '该时点尚无已采集的 ETF 行情')
        result['stale'] = False
    else:
        result = await load(date)
    # On a cold database allow collection to complete; thereafter reads are independent.
    data = await asyncio.to_thread(service.national_team, result['payload'], cutoff)
    if not known_at and not any(row['report_date'] for row in data['coverage']):
        try:
            await asyncio.wait_for(service.collect_holdings([r['code'] for r in result['payload']['etfs']]), timeout=35)
        except asyncio.TimeoutError:
            pass
        data = await asyncio.to_thread(service.national_team, result['payload'])
    return {**data, 'stale': result['stale']}


@router.get('/observations')
def observations(resource: Literal['board', 'holdings', 'signals', 'dates'] = 'board',
                 before_id: int | None = Query(None, ge=1), limit: int = Query(20, ge=1, le=100),
                 known_at: datetime | None = None):
    if known_at and known_at.tzinfo is None:
        raise HTTPException(422, 'known_at 必须包含时区')
    with SessionLocal() as db:
        query = select(EtfSnapshot).where(EtfSnapshot.resource == resource)
        if before_id:
            query = query.where(EtfSnapshot.id < before_id)
        if known_at:
            query = query.where(EtfSnapshot.observed_at <= known_at.astimezone(timezone.utc).isoformat())
        rows = db.scalars(query.order_by(EtfSnapshot.id.desc()).limit(limit + 1)).all()
        return {'items': [{'id': r.id, 'resource': r.resource, 'key': r.key, 'source': r.source,
                'source_url': r.source_url, 'source_updated_at': r.source_updated_at, 'observed_at': r.observed_at,
                'checksum': r.checksum, 'payload': r.payload} for r in rows[:limit]],
                'next_before_id': rows[limit - 1].id if len(rows) > limit else None,
                'units': {'board_money': '100000000 CNY', 'board_shares_delta': '100000000 units',
                          'holding_shares': 'units', 'holding_ratio': 'percent', 'signals_money': 'CNY'}}
