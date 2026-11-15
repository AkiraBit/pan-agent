"""Authenticated ETF read API, including versioned observations for analysis agents."""
import asyncio
from datetime import date as Date, datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query

from src.platform.persistence.database import SessionLocal
from src.modules.market.etf import history as history_service, service, sources

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
def observations(resource: Literal['board', 'holdings', 'signals', 'dates', 'turnover', 'shares', 'nav', 'price', 'pcf', 'derived'] = 'board',
                 before_id: int | None = Query(None, ge=1), limit: int = Query(20, ge=1, le=100),
                 known_at: datetime | None = None, source: str | None = None):
    if known_at and known_at.tzinfo is None:
        raise HTTPException(422, 'known_at 必须包含时区')
    from src.modules.market.etf.observations import read_observations
    with SessionLocal() as db:
        return read_observations(db, resource=resource, before_id=before_id, limit=limit,
                                 known_at=known_at, source=source)


@router.get('/history')
async def history(period: Literal['1m', '3m', '6m', '1y', 'all', 'custom'] = '3m',
                  start: Date | None = None, end: Date | None = None,
                  scope: Literal['market', 'national'] = 'market',
                  code: str | None = Query(None, pattern=r'^\d{6}$'),
                  institution: Literal['huijin', 'csf', 'guoxin', 'chengtong'] | None = None,
                  known_at: datetime | None = None):
    requested_start, requested_end = validate_date(start), validate_date(end)
    if requested_start and requested_end and requested_start > requested_end:
        raise HTTPException(422, '开始日期不能晚于结束日期')
    if period == 'custom' and (not start or not end):
        raise HTTPException(422, '请选择完整的日期范围')
    if known_at and known_at.tzinfo is None:
        raise HTTPException(422, 'known_at 必须包含时区')
    cutoff = known_at.astimezone(timezone.utc).isoformat() if known_at else None
    if cutoff:
        latest = await asyncio.to_thread(service.saved_board, None, cutoff)
        if latest is None:
            raise HTTPException(404, '该时点尚无已采集的 ETF 行情')
        catalog = await asyncio.to_thread(history_service.stored_dates, cutoff)
    else:
        latest = await load()
        try:
            catalog = await service.dates()
        except history_service.PROVIDER_ERRORS:
            catalog = await asyncio.to_thread(history_service.stored_dates)
    last = requested_end or latest['payload']['date']
    first = requested_start or ('2000-01-01' if period == 'all' else history_service.months_before(last, {'1m': 1, '3m': 3, '6m': 6, '1y': 12}.get(period, 3)))
    if first > last:
        raise HTTPException(422, '开始日期不能晚于结束日期')
    codes = [r['code'] for r in latest['payload']['etfs'] if not code or r['code'] == code]
    if not codes:
        raise HTTPException(404, 'ETF 不在当前观察范围')
    key = ('history', first, last, scope, code)
    if not cutoff:
        days = sorted(day for day in catalog if first <= day <= last)
        try:
            await asyncio.wait_for(service.coalesce(key, lambda: history_service.collect_range(days, codes, first, last, scope == 'national', requested_start)), timeout=2)
        except asyncio.TimeoutError:
            pass  # collection continues, and the next read returns the persisted progress
    result = await asyncio.to_thread(history_service.read_history, first, last, catalog, national=scope == 'national',
                                     code=code, institution=institution, cutoff=cutoff)
    if period == 'all':
        actual = [p['date'] for p in result['series']] + [p['date'] for p in result['holdings_trend']]
        result['range']['start'] = min(actual) if actual else last
    return {**result, 'period': period, 'scope': scope, 'collecting': key in service._inflight,
            'stale': latest.get('stale', False), 'available_start': min(catalog) if catalog else None,
            'available_end': max(catalog) if catalog else None}
