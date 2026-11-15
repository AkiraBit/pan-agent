"""Latest-only overview read model, using the existing durable run lease."""
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from src.modules.administration import builtin_skills
from src.platform.persistence.models import EmotionContextNote, EmotionOverview, EmotionRun, EmotionWorkspace
from .analysis import reference_day
from .facts import utc_now
from .repository import EmotionRepository, WorkspaceError, note_dto, run_dto

SKILL_ID = 'analyze-a-share-sentiment'


class OverviewRepository:
    def __init__(self, db):
        self.db = db

    def view(self, now=None):
        now = now or utc_now()
        row = self.db.get(EmotionOverview, 1)
        payload = deepcopy(row.payload) if row else None
        workspace = self.db.get(EmotionWorkspace, 1)
        active = self.db.query(EmotionRun).filter(EmotionRun.status.in_(['queued', 'running'])).first()
        latest = self.db.query(EmotionRun).filter(EmotionRun.inputs['kind'].as_string() == 'overview').order_by(EmotionRun.created_at.desc()).first()
        skill = builtin_skills.status(self.db, SKILL_ID)
        stale = not payload or datetime.fromisoformat(payload['refresh_after']) <= now or payload['input_version'] != (workspace.input_version if workspace else 0)
        # A failed automatic attempt is not retried on every poll or browser mount.
        retry_after = (datetime.fromisoformat(latest.finished_at) + timedelta(minutes=10)).isoformat() if latest and latest.finished_at and latest.status in {'failed', 'interrupted', 'cancelled'} else None
        return {'overview': payload, 'stale': bool(stale), 'active_run': run_dto(active) if active else None,
                'last_run': run_dto(latest) if latest else None,
                'can_analyze': skill['available'], 'skill_enabled': skill['enabled'],
                'connection_status': skill['connection_status'], 'retry_after': retry_after,
                'server_time': now.isoformat()}

    def create(self, body, now=None):
        now = now or utc_now()
        old = self.db.query(EmotionRun).filter_by(workspace_id=1, request_key=body.request_key).first()
        if old:
            return old, False
        view = self.view(now)
        if not view['can_analyze']:
            raise WorkspaceError('overview_skill_unavailable')
        if view['active_run']:
            return self.db.get(EmotionRun, view['active_run']['id']), False
        if not body.force and (not view['stale'] or (view['retry_after'] and datetime.fromisoformat(view['retry_after']) > now)):
            return None, False
        repository = EmotionRepository(self.db)
        workspace = repository.ensure_workspace()
        row = EmotionRun(id=uuid4().hex, workspace_id=1, request_key=body.request_key, status='queued',
                         target_trade_date=reference_day(now), created_at=now.isoformat(),
                         base_revision=workspace.revision, input_version=workspace.input_version,
                         inputs={'kind': 'overview', 'language': body.language, 'settings': deepcopy(workspace.settings),
                                 'notes': [note_dto(n) for n in self.db.query(EmotionContextNote).filter_by(workspace_id=1, status='open').all()],
                                 'previous': view['overview']}, events=[])
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            active = self.db.query(EmotionRun).filter(EmotionRun.status.in_(['queued', 'running'])).first()
            if active:
                return active, False
            raise WorkspaceError('analysis_running') from None
        return row, True

    def publish(self, identity, facts, analysis, model_label):
        repository = EmotionRepository(self.db)
        run = repository.get_run(identity)
        claimed = self.db.execute(update(EmotionRun).where(
            EmotionRun.id == identity, EmotionRun.status == 'running',
        ).values(status='succeeded'))
        if claimed.rowcount != 1:
            self.db.rollback()
            raise WorkspaceError('run_cancelled')
        matched = self.db.execute(update(EmotionWorkspace).where(
            EmotionWorkspace.id == 1, EmotionWorkspace.input_version == run.input_version,
        ).values(input_version=EmotionWorkspace.input_version))
        if matched.rowcount != 1:
            self.db.rollback()
            raise WorkspaceError('inputs_changed')
        if not builtin_skills.status(self.db, SKILL_ID)['available']:
            self.db.rollback()
            raise WorkspaceError('overview_skill_unavailable')
        payload = {k: deepcopy(v) for k, v in facts.items() if k != 'raw'}
        payload.update(schema_version='1.0', run_id=identity, input_version=run.input_version,
                       analysis=analysis, analyzed_at=utc_now().isoformat(), model_label=model_label,
                       skill={'id': SKILL_ID, 'version': builtin_skills.definition(SKILL_ID)['version']})
        row = self.db.get(EmotionOverview, 1)
        if row:
            row.payload = payload
        else:
            self.db.add(EmotionOverview(id=1, payload=payload))
        run.status, run.finished_at, run.model_label = 'succeeded', utc_now().isoformat(), model_label
        run.target_trade_date = facts['trade_date']
        self.db.commit()
        return payload
