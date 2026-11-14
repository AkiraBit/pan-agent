"""Append-only primary-source event versions, shared across published plans."""
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from src.platform.persistence.models import EmotionRegulatoryEvent


class RegulatoryRepository:
    def __init__(self, db):
        self.db = db

    def retain(self, events):
        for event in events:
            if not self.db.get(EmotionRegulatoryEvent,event['id']):
                self.db.add(EmotionRegulatoryEvent(id=event['id'],symbol=event['symbol'],
                    known_at=datetime.fromisoformat(event['known_at']).astimezone(timezone.utc).isoformat(),payload=deepcopy(event)))
        try:self.db.commit()
        except IntegrityError:self.db.rollback()  # Concurrent refresh; immutable IDs deduplicate.

    def read(self, symbols, cutoff):
        rows=self.db.query(EmotionRegulatoryEvent).filter(EmotionRegulatoryEvent.symbol.in_(symbols),
            EmotionRegulatoryEvent.known_at<=datetime.fromisoformat(cutoff).astimezone(timezone.utc).isoformat()).order_by(EmotionRegulatoryEvent.known_at).all()
        return [deepcopy(r.payload) for r in rows]
