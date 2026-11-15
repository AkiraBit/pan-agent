"""Automatic Longbridge daily-turnover backfill using the saved OAuth connection.

Amounts are CNY, not volume (lots) or the board's 100-million-CNY display unit.
Only completed trading days are supplemented; original board snapshots stay raw.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, or_, select

from src.modules.administration import longbridge_mcp
from src.platform.persistence.models import MCPConnection
from . import service, sources
from .models import EtfDaily, EtfSnapshot, EtfTurnover

TOOL = 'history_candlesticks_by_date'
DOCS_URL = 'https://open.longbridge.com/docs/mcp/tools#history_candlesticks_by_date'


def symbol(code):
    if not re.fullmatch(r'(?:5|1)\d{5}', code):
        raise ValueError('Unsupported ETF code')
    return code + ('.SZ' if code.startswith('1') else '.SH')


def last_closed_day():
    now = datetime.now(sources.CN)
    # Wait for the daily bar to settle; this is not an intraday quote fallback.
    return (now.date() if (now.hour, now.minute) >= (15, 15) else now.date() - timedelta(days=1)).isoformat()


def decode(result, code, start, end):
    """Reject malformed/error responses atomically; never turn gaps into zeroes."""
    if not isinstance(result, dict) or result.get('isError'):
        raise ValueError('Longbridge tool failed')
    data = result.get('structuredContent')
    if data is None:
        data = json.loads(''.join(block['text'] for block in result.get('content', []) if block.get('type') == 'text'))
    if isinstance(data, dict) and data.get('error_code'):
        if data['error_code'] == 429002:
            raise RateLimited()
        raise ValueError('Longbridge data unavailable')
    if not isinstance(data, list):
        raise ValueError('Missing Longbridge bars')
    rows, seen = [], set()
    for bar in data:
        if not isinstance(bar, dict):
            raise ValueError('Invalid daily bar')
        if bar.get('symbol', symbol(code)) != symbol(code):
            raise ValueError('ETF symbol mismatch')
        stamp = datetime.fromisoformat(bar['timestamp'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Missing exchange timezone')
        day = stamp.astimezone(sources.CN).date().isoformat()
        if not start <= day <= end or day in seen:
            raise ValueError('Unexpected or duplicate trading date')
        seen.add(day)
        amount = sources.finite(bar.get('turnover'), nonnegative=True)
        if amount is not None:
            rows.append({'code': code, 'date': day, 'turnover_cny': amount, 'bar': bar})
    return rows


class RateLimited(ValueError):
    pass


async def fetch(code, start, end):
    arguments = {'symbol': symbol(code), 'period': 'day', 'start': start, 'end': end,
                 'forward_adjust': False, 'trade_sessions': 'intraday'}
    for attempt in range(3):
        with service.SessionLocal() as db:
            result = await longbridge_mcp.remote(db, TOOL, arguments)
        try:
            return decode(result, code, start, end)
        except RateLimited:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)


def observations(db, cutoff=None, day=None):
    query = select(func.max(EtfSnapshot.id)).where(EtfSnapshot.resource == 'turnover')
    if cutoff:
        query = query.where(EtfSnapshot.observed_at <= cutoff)
    if day:
        query = query.where(EtfSnapshot.key.like('%:' + day))
    snapshots = db.scalars(select(EtfSnapshot).where(EtfSnapshot.id.in_(query.group_by(EtfSnapshot.key)))).all()
    return {(s.payload['code'], s.payload['date']): s for s in snapshots}


def overlay(payload, supplements):
    rows, evidence = [], []
    for original in payload['etfs']:
        row = dict(original)
        saved = supplements.get((row['code'], payload['date']))
        if row.get('amount') is None and saved:
            row.update(amount=saved.payload['turnover_cny'] / 1e8, amount_source='longbridge',
                       amount_snapshot_id=saved.id)
            evidence.append(saved.id)
        rows.append(row)
    result = {**payload, 'etfs': rows, 'amount_snapshot_ids': evidence}
    if result.get('amount') is None and rows and all(r.get('amount') is not None for r in rows):
        result['amount'] = sum(r['amount'] for r in rows)
        result['amount_source'] = 'etf_sum'
    return result


def save(rows, requested_days):
    count = 0
    with service.SessionLocal() as db:
        for row in rows:
            if row['date'] not in requested_days:
                continue
            daily = db.get(EtfDaily, (row['code'], row['date']))
            if daily is None:
                continue
            payload = {**row, 'symbol': symbol(row['code']), 'period': 'day',
                       'adjustment': 'none', 'currency': 'CNY', 'tool': TOOL}
            snap = service.snapshot(db, 'turnover', f"{row['code']}:{row['date']}", payload,
                                    'longbridge', DOCS_URL)
            service.upsert(db, EtfTurnover, [{'code': row['code'], 'trade_date': row['date'],
                           'turnover_cny': row['turnover_cny'], 'snapshot_id': snap.id,
                           'checked_at': service.timestamp()}], ['code', 'trade_date'])
            # Preserve provider precedence even if a board arrived during the request.
            from .free_store import original_row
            original = original_row(db, daily)
            if original.get('amount') is None:
                daily.turnover_cny = row['turnover_cny']
                count += 1
        db.commit()
    return count


def pending():
    from src.platform.marketdata.longbridge import enabled
    if not enabled('etf_turnover', service.SessionLocal):
        return {}
    now = datetime.fromisoformat(service.timestamp())
    recent = (now.astimezone(sources.CN).date() - timedelta(days=7)).isoformat()
    with service.SessionLocal() as db:
        connection = db.get(MCPConnection, 'longbridge')
        if not connection or not connection.enabled or not connection.credentials:
            return {}
        rows = db.execute(select(EtfDaily.code, EtfDaily.trade_date).outerjoin(EtfTurnover,
            and_(EtfDaily.code == EtfTurnover.code, EtfDaily.trade_date == EtfTurnover.trade_date))
            .where(EtfDaily.trade_date <= last_closed_day(), or_(EtfDaily.turnover_cny.is_(None),
                and_(EtfDaily.trade_date >= recent, EtfTurnover.checked_at < (now - timedelta(hours=1)).isoformat())))
            .order_by(EtfDaily.code, EtfDaily.trade_date)).all()
    result = {}
    for code, day in rows:
        result.setdefault(code, []).append(day)
    return result


def batches(days):
    """Bound API ranges to 90 calendar days to avoid silently truncated history."""
    batch = []
    for day in sorted(set(days)):
        if batch and (date.fromisoformat(day) - date.fromisoformat(batch[0])).days >= 90:
            yield batch
            batch = []
        batch.append(day)
    if batch:
        yield batch


async def collect():
    from src.platform.marketdata.longbridge import enabled
    async def run():
        written = 0
        for code, days in (await asyncio.to_thread(pending)).items():
            key = ('turnover', code)
            if time.monotonic() < service._retry.get(key, 0):
                continue
            for batch in batches(days):
                if not await asyncio.to_thread(enabled, 'etf_turnover', service.SessionLocal):
                    return written  # Disabling the source stops the next request in a running backfill.
                try:
                    rows = await fetch(code, batch[0], batch[-1])
                    written += await asyncio.to_thread(save, rows, set(batch))
                    if set(batch) - {r['date'] for r in rows}:
                        service._retry[key] = time.monotonic() + 300
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Never log provider bodies, tokens or account data.
                    service.log.warning('ETF Longbridge turnover unavailable: %s', code)
                    service._retry[key] = time.monotonic() + 300
                    break
                await asyncio.sleep(.35)
        return written
    return await service.coalesce(('turnover',), run)
