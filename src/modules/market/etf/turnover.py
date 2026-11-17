"""Supplement daily ETF turnover with completed Tonghuashun snapshots.

Amounts are CNY, not volume (lots) or the board's 100-million-CNY display unit.
Only completed trading days are supplemented; original board snapshots stay raw.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, or_, select

from src.platform.marketdata import fuyao_business, fuyao_credentials, fuyao_rest
from src.platform.marketdata.source_activation import active_source
from src.platform.persistence.models import DataSource
from . import service, sources
from .models import EtfDaily, EtfSnapshot, EtfTurnover

OPERATION = "get_fund_market_snapshot"


def symbol(code):
    if not re.fullmatch(r'(?:5|1)\d{5}', code):
        raise ValueError('Unsupported ETF code')
    return code + ('.SZ' if code.startswith('1') else '.SH')


def last_closed_day():
    now = datetime.now(sources.CN)
    # Wait for the daily bar to settle; this is not an intraday quote fallback.
    return (now.date() if (now.hour, now.minute) >= (15, 15) else now.date() - timedelta(days=1)).isoformat()


def configured_sources():
    with service.SessionLocal() as db:
        if fuyao_credentials.configured(fuyao_credentials.read(db)) and db.scalar(select(DataSource.id).where(
            DataSource.provider == "fuyao", DataSource.type == fuyao_rest.TYPE_PREFIX + OPERATION, active_source(),
        ).limit(1)):
            return ["fuyao"]
        return []


async def fetch_fuyao(code, start, end):
    data = await fuyao_business.fetch(OPERATION, {"thscode": symbol(code)})
    if not isinstance(data, dict) or type(data.get("timestamp")) is not int:
        return []
    stamp = datetime.fromtimestamp(data["timestamp"] / 1000, sources.CN)
    day = stamp.date().isoformat()
    # An intraday cumulative value is not a completed daily observation.
    if (stamp.hour, stamp.minute) < (15, 0) or not start <= day <= end:
        return []
    return [{"code": code, "date": day, "turnover_cny": amount, "bar": row}
            for row in data.get("item", []) if row.get("thscode") == symbol(code)
            and (amount := sources.finite(row.get("turnover"), nonnegative=True)) is not None][:1]


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
            row.update(amount=saved.payload['turnover_cny'] / 1e8, amount_source=saved.source,
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
                       'adjustment': 'none', 'currency': 'CNY', 'tool': OPERATION}
            snap = service.snapshot(db, 'turnover', f"{row['code']}:{row['date']}", payload,
                                    "fuyao", fuyao_rest.OPERATIONS[OPERATION]["docs_url"])
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
    if not configured_sources():
        return {}
    now = datetime.fromisoformat(service.timestamp())
    recent = (now.astimezone(sources.CN).date() - timedelta(days=7)).isoformat()
    with service.SessionLocal() as db:
        query = (select(EtfDaily.code, EtfDaily.trade_date).outerjoin(EtfTurnover,
            and_(EtfDaily.code == EtfTurnover.code, EtfDaily.trade_date == EtfTurnover.trade_date))
            .where(EtfDaily.trade_date <= last_closed_day(), or_(EtfDaily.turnover_cny.is_(None),
                and_(EtfDaily.trade_date >= recent, EtfTurnover.checked_at < (now - timedelta(hours=1)).isoformat())))
            .order_by(EtfDaily.code, EtfDaily.trade_date))
        query = query.where(EtfDaily.trade_date == select(func.max(EtfDaily.trade_date)).where(
            EtfDaily.trade_date <= last_closed_day()).scalar_subquery())
        rows = db.execute(query).all()
    result = {}
    for code, day in rows:
        result.setdefault(code, []).append(day)
    return result


async def collect():
    async def run():
        written = 0
        for code, days in (await asyncio.to_thread(pending)).items():
            key = ('turnover', code)
            day = days[0]  # Snapshot endpoint only covers the latest session.
            if time.monotonic() < service._retry.get(key, 0) or (
                date.fromisoformat(last_closed_day()) - date.fromisoformat(day)
            ).days > 7:
                continue
            if not await asyncio.to_thread(configured_sources):
                return written  # Recheck after each request in case the source was disabled.
            try:
                rows = await fetch_fuyao(code, day, day)
                written += await asyncio.to_thread(save, rows, {day})
                if not rows:
                    service._retry[key] = time.monotonic() + 300
            except Exception:
                service.log.warning('ETF turnover unavailable: fuyao/%s', code)
                service._retry[key] = time.monotonic() + 300
            await asyncio.sleep(.35)
        return written
    return await service.coalesce(('turnover',), run)
