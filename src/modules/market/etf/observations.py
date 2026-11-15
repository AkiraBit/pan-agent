"""Shared read service for saved ETF observations, independent of HTTP routes."""
from datetime import timezone

from sqlalchemy import select

from .models import EtfSnapshot


def read_observations(db, *, resource="board", before_id=None, limit=20, known_at=None, source=None):
    query = select(EtfSnapshot).where(EtfSnapshot.resource == resource)
    if source:
        query = query.where(EtfSnapshot.source == source)
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
                      'holding_shares': 'units', 'holding_ratio': 'percent', 'signals_money': 'CNY',
                      'turnover_money': 'CNY', 'public_money': 'CNY', 'public_shares': 'units'}}
