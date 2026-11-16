"""Align observed index closes to ETF trading days and use one comparison baseline."""
from math import isfinite

from sqlalchemy import func, select

from .free_sources import BENCHMARK_CODES
from .models import EtfMeasurement, EtfSnapshot


def comparison(db, days, cutoff=None):
    if not days:
        return None, {}
    start, end = days[0], days[-1]
    observations = {}

    def add(code, day, close, snapshot_id):
        if start <= day <= end and isinstance(close, (int, float)) and isfinite(close) and close > 0:
            observations.setdefault(day, {})[code] = {'close': close, 'snapshot_id': snapshot_id}

    if cutoff:
        # The current measurement can have been revised after the requested cutoff.
        # Replay the versions of these three histories that were actually known then.
        query = select(EtfSnapshot.id, EtfSnapshot.payload).where(
            EtfSnapshot.resource == 'price', EtfSnapshot.source == 'tencent',
            func.json_extract(EtfSnapshot.payload, '$.request.code').in_(BENCHMARK_CODES),
            EtfSnapshot.observed_at <= cutoff,
        ).order_by(EtfSnapshot.id)
        for snapshot_id, payload in db.execute(query):
            for row in payload['rows']:
                add(row['code'], row['date'], row['close'], snapshot_id)
    else:
        query = select(
            EtfMeasurement.code, EtfMeasurement.trade_date,
            EtfMeasurement.payload['close'].as_float(), EtfMeasurement.snapshot_id,
        ).where(
            EtfMeasurement.resource == 'price', EtfMeasurement.source == 'tencent',
            EtfMeasurement.code.in_(BENCHMARK_CODES), EtfMeasurement.trade_date.between(start, end),
        )
        for row in db.execute(query):
            add(*row)

    base_date = next((day for day in days if all(code in observations.get(day, {}) for code in BENCHMARK_CODES)), None)
    base = observations.get(base_date, {})
    result = {}
    for day in days:
        result[day] = {
            code: {**item, 'return_percent': (item['close'] / base[code]['close'] - 1) * 100
                   if base_date is not None and day >= base_date else None}
            for code, item in observations.get(day, {}).items()
        }
    return base_date, result
