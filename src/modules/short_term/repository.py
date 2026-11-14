"""Transactions for immutable publications and installation-scoped memory."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from src.platform.persistence.models import EmotionWorkspace, EmotionRun, EmotionPublication, EmotionContextNote, EmotionSessionValidation
from src.platform.scheduling.trading_calendar import is_trading_day
from .facts import utc_now, next_trade_date, evidence
from .schemas import WorkspaceSettings


class WorkspaceError(ValueError):
    pass


def note_dto(note):
    return {"id": note.id, "content": note.content, "source_url": note.source_url,
            "created_at": note.created_at, "status": note.status, "verification": "user_unverified"}


def run_dto(run):
    return {k: getattr(run, k) for k in ('id', 'status', 'target_trade_date', 'created_at', 'finished_at',
                                        'base_revision', 'model_label', 'error_code', 'events', 'publication_id')}


class EmotionRepository:
    def __init__(self, db):
        self.db = db

    def ensure_workspace(self):
        row = self.db.get(EmotionWorkspace, 1)
        if row is None:
            try:
                self.db.add(EmotionWorkspace(id=1, revision=0, input_version=0, settings=WorkspaceSettings().model_dump()))
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
            row = self.db.get(EmotionWorkspace, 1)
        return row

    def workspace(self):
        row = self.db.get(EmotionWorkspace, 1)
        publication = self.db.get(EmotionPublication, row.current_publication_id) if row and row.current_publication_id else None
        history = self.db.query(EmotionPublication).order_by(EmotionPublication.revision.desc()).limit(50).all()
        runs = self.db.query(EmotionRun).order_by(EmotionRun.created_at.desc()).limit(12).all()
        notes = self.db.query(EmotionContextNote).order_by(EmotionContextNote.created_at.desc()).limit(100).all()
        validation = self.db.query(EmotionSessionValidation).order_by(EmotionSessionValidation.enabled.desc(),EmotionSessionValidation.created_at.desc()).first()
        try:
            target = next_trade_date(utc_now())
        except ValueError:
            target = None
        return {"publication": deepcopy(publication.payload) if publication else None,
                "settings": WorkspaceSettings.model_validate(row.settings if row else {}).model_dump(),
                "input_version": row.input_version if row else 0, "target_trade_date": target,
                "server_time": utc_now().isoformat(), "validation_trade_date": validation.trade_date if validation else None,
                "history": [{"id": h.id, "revision": h.revision, "target_trade_date": h.target_trade_date,
                             "published_at": h.published_at, "title": h.payload['analysis']['title']} for h in history],
                "runs": [run_dto(r) for r in runs], "notes": [note_dto(n) for n in notes]}

    def publication(self, identity):
        row = self.db.get(EmotionPublication, identity)
        if row is None:
            raise WorkspaceError("publication_not_found")
        return deepcopy(row.payload)

    def save_settings(self, settings):
        row = self.ensure_workspace()
        self.db.execute(update(EmotionWorkspace).where(EmotionWorkspace.id == row.id).values(
            settings=settings.model_dump(), input_version=EmotionWorkspace.input_version + 1))
        self.db.commit()
        return settings.model_dump()

    def add_context(self, body):
        self.ensure_workspace()
        count = self.db.query(EmotionContextNote).filter_by(workspace_id=1, status='open').count()
        if count >= 20:
            raise WorkspaceError("context_limit")
        row = EmotionContextNote(id=uuid4().hex, workspace_id=1, content=body.content, source_url=body.source_url,
                                 created_at=utc_now().isoformat(), status='open')
        self.db.add(row)
        self.db.execute(update(EmotionWorkspace).where(EmotionWorkspace.id == 1).values(input_version=EmotionWorkspace.input_version + 1))
        self.db.commit()
        return note_dto(row)

    def update_context(self, identity, status):
        row = self.db.get(EmotionContextNote, identity)
        if not row:
            raise WorkspaceError("context_not_found")
        if status == 'open' and row.status != 'open' and self.db.query(EmotionContextNote).filter_by(status='open').count() >= 20:
            raise WorkspaceError("context_limit")
        row.status = status
        self.db.execute(update(EmotionWorkspace).where(EmotionWorkspace.id == 1).values(input_version=EmotionWorkspace.input_version + 1))
        self.db.commit()
        return note_dto(row)

    def frozen_memory(self):
        rows = self.db.query(EmotionPublication).order_by(EmotionPublication.revision.desc()).limit(7).all()
        return [{"publication_id": r.id, "revision": r.revision, "target_trade_date": r.target_trade_date,
                 "published_at": r.published_at, "knowledge_cutoff": r.payload['knowledge_cutoff'],
                 "summary": r.payload['analysis']['memory_summary'],
                 "open_questions": r.payload['analysis']['open_questions'],
                 "cycles": r.payload['analysis']['cycles'],
                 "symbols": [s['symbol'] for s in r.payload['analysis']['watchlist']]} for r in rows]

    def create_run(self, body, *, now=None):
        now = now or utc_now()
        old = self.db.query(EmotionRun).filter_by(workspace_id=1, request_key=body.request_key).first()
        if old:
            return old, False
        workspace = self.ensure_workspace()
        if self.db.query(EmotionRun).filter(EmotionRun.status.in_(['queued', 'running'])).first():
            raise WorkspaceError("analysis_running")
        target = body.target_trade_date.isoformat() if body.target_trade_date else next_trade_date(now)
        earliest = next_trade_date(now)
        if target < earliest or target > (now.date() + timedelta(days=14)).isoformat() or not is_trading_day('CN', datetime.fromisoformat(target).date()):
            raise WorkspaceError("target_date_invalid")
        from .lifecycle_repository import LifecycleRepository
        from .regulatory_repository import RegulatoryRepository
        memory = self.frozen_memory()
        regulatory_symbols = list(dict.fromkeys([*workspace.settings.get('focus_symbols', []), *[s for m in memory for s in m['symbols']]]))
        # Persist the exact input scope; later notes cannot silently enter this run.
        notes = self.db.query(EmotionContextNote).filter_by(workspace_id=1, status='open').order_by(EmotionContextNote.created_at).all()
        row = EmotionRun(id=uuid4().hex, workspace_id=1, request_key=body.request_key, status='queued',
                         target_trade_date=target, created_at=now.isoformat(), base_revision=workspace.revision,
                         input_version=workspace.input_version,
                         inputs={"settings": deepcopy(workspace.settings), "notes": [note_dto(n) for n in notes],
                                 "memory": memory, "regulatory_memory": RegulatoryRepository(self.db).read(regulatory_symbols, now.isoformat()), "reviews": LifecycleRepository(self.db).review_memory(), "language": body.language}, events=[])
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            old = self.db.query(EmotionRun).filter_by(workspace_id=1, request_key=body.request_key).first()
            if old:
                return old, False
            raise WorkspaceError("analysis_running") from None
        return row, True

    def get_run(self, identity):
        row = self.db.get(EmotionRun, identity)
        if not row:
            raise WorkspaceError("run_not_found")
        return row

    def claim_run(self, identity):
        result = self.db.execute(update(EmotionRun).where(EmotionRun.id == identity, EmotionRun.status == 'queued').values(status='running'))
        self.db.commit()
        return bool(result.rowcount)

    def append_event(self, identity, kind, data):
        row = self.get_run(identity)
        events = list(row.events or [])
        events.append({"seq": (events[-1]['seq'] if events else 0) + 1, "type": kind,
                       "at": utc_now().isoformat(), "data": data})
        row.events = events[-100:]
        self.db.commit()

    def save_facts(self, identity, facts):
        row = self.get_run(identity)
        if row.status != 'running':
            raise WorkspaceError("run_cancelled")
        row.facts = facts
        self.db.commit()

    def finish_failed(self, identity, code, status='failed'):
        self.db.execute(update(EmotionRun).where(EmotionRun.id == identity, EmotionRun.status.in_(['queued', 'running'])).values(
            status=status, error_code=code, finished_at=utc_now().isoformat()))
        self.db.commit()

    def publish(self, identity, publication, model_label):
        run = self.get_run(identity)
        claimed = self.db.execute(update(EmotionRun).where(
            EmotionRun.id == identity, EmotionRun.status == 'running',
        ).values(status='succeeded'))
        if claimed.rowcount != 1:
            self.db.rollback()
            raise WorkspaceError("run_cancelled")
        publication_id = uuid4().hex
        revision = run.base_revision + 1
        result = self.db.execute(update(EmotionWorkspace).where(
            EmotionWorkspace.id == 1, EmotionWorkspace.revision == run.base_revision,
            EmotionWorkspace.input_version == run.input_version,
        ).values(revision=revision, current_publication_id=publication_id))
        if result.rowcount != 1:
            self.db.rollback()
            raise WorkspaceError("inputs_changed")
        payload = {**publication, "id": publication_id, "revision": revision, "run_id": identity,
                   "parent_revision": run.base_revision, "input_version": run.input_version,
                   "published_at": utc_now().isoformat(), "model_label": model_label}
        self.db.add(EmotionPublication(id=publication_id, workspace_id=1, run_id=identity,
                                      revision=revision, target_trade_date=run.target_trade_date,
                                      published_at=payload['published_at'], payload=payload))
        run.publication_id = publication_id
        run.model_label = model_label
        run.finished_at = payload['published_at']
        self.db.commit()
        return payload

    def recover(self):
        self.db.query(EmotionRun).filter(EmotionRun.status.in_(['queued', 'running'])).update(
            {'status': 'interrupted', 'error_code': 'worker_restarted', 'finished_at': utc_now().isoformat()})
        self.db.commit()


def contextual_evidence(inputs, observed):
    result = []
    for note in inputs['notes']:
        result.append(evidence('note:' + note['id'], 'user_context', note['content'][:100], 'user',
                               {'text': note['content'], 'verification': 'user_unverified'}, observed,
                               published=note['created_at'], url=note['source_url'], status='user_unverified'))
    for memory in inputs['memory']:
        result.append(evidence('memory:' + memory['publication_id'], 'prior_analysis',
                               f"v{memory['revision']} / {memory['target_trade_date']}", 'panwatch', memory, observed,
                               published=memory['published_at'], status='prior_hypothesis'))
    for review in inputs.get('reviews', []):
        result.append(evidence('review:' + review['review_id'], 'prior_review', review['target_trade_date'],
                               'panwatch', review, observed, published=review['published_at'], status='prior_observation_review'))
    return result
