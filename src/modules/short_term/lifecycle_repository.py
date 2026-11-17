"""Append-only observations and postmarket reviews linked to an immutable plan."""
from copy import deepcopy
from datetime import datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from marketdata.short_term import TZ
from src.platform.marketdata import fuyao_business
from src.platform.persistence.models import (EmotionMonitor, EmotionObservation, EmotionReview,
                                            EmotionRun)
from .facts import utc_now, evidence
from .repository import EmotionRepository, WorkspaceError
from .verification import next_session


class LifecycleRepository:
    def __init__(self, db):
        self.db = db
        self.base = EmotionRepository(db)

    def source_config(self):
        enabled = "get_a_share_auction_snapshot" in fuyao_business.active_operations(self.db)
        return {"enabled": enabled, "provider_name": "fuyao"}

    def set_monitor(self, publication_id, enabled, *, now=None):
        now = now or utc_now()
        publication = self.base.publication(publication_id)
        following = next_session(publication['target_trade_date'])
        if enabled and (not following or now.astimezone(TZ).date().isoformat() > following):
            raise WorkspaceError('monitor_window_expired')
        row = self.db.query(EmotionMonitor).filter_by(publication_id=publication_id).first()
        if not row:
            row = EmotionMonitor(id=uuid4().hex, publication_id=publication_id,
                                 target_trade_date=publication['target_trade_date'], created_at=now.isoformat())
            self.db.add(row)
        row.status = 'active' if enabled else 'paused'
        row.lease_token = row.lease_until = None
        if enabled:
            self.db.query(EmotionMonitor).filter(EmotionMonitor.target_trade_date==row.target_trade_date,
                EmotionMonitor.publication_id!=publication_id, EmotionMonitor.status=='active').update({'status':'superseded'})
        self.db.commit()
        return self.view(publication_id)

    def active(self):
        return [{'id':r.id,'publication_id':r.publication_id,'target_trade_date':r.target_trade_date,
                 'last_sample_at':r.last_sample_at} for r in self.db.query(EmotionMonitor).filter_by(status='active').all()]

    def claim(self, identity, now, slot):
        if self.db.query(EmotionObservation).filter_by(monitor_id=identity,slot=slot).first():
            return None
        token = uuid4().hex
        result = self.db.execute(update(EmotionMonitor).where(EmotionMonitor.id==identity,
            EmotionMonitor.status=='active', or_(EmotionMonitor.lease_until.is_(None),EmotionMonitor.lease_until < now.isoformat())
            ).values(lease_token=token,lease_until=(now+timedelta(seconds=90)).isoformat()))
        self.db.commit()
        return token if result.rowcount else None

    def save_sample(self, identity, token, slot, payload):
        result = self.db.execute(update(EmotionMonitor).where(EmotionMonitor.id==identity,
            EmotionMonitor.lease_token==token,EmotionMonitor.status=='active').values(
                lease_token=None,lease_until=None,last_sample_at=payload['observed_at'],last_error=None))
        if not result.rowcount:
            self.db.rollback();return False
        self.db.add(EmotionObservation(id=payload['id'],monitor_id=identity,slot=slot,
                                      observed_at=payload['observed_at'],payload=payload))
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback();return False
        return True

    def release(self, identity, token, error):
        self.db.execute(update(EmotionMonitor).where(EmotionMonitor.id==identity,EmotionMonitor.lease_token==token)
                        .values(lease_token=None,lease_until=None,last_error=error))
        self.db.commit()

    def complete(self, identity):
        self.db.execute(update(EmotionMonitor).where(EmotionMonitor.id==identity).values(status='complete',lease_token=None,lease_until=None))
        self.db.commit()

    def recover(self):
        self.db.query(EmotionMonitor).update({'lease_token':None,'lease_until':None})
        self.db.commit()

    def latest(self, monitor_id):
        row = self.db.query(EmotionObservation).filter_by(monitor_id=monitor_id).order_by(EmotionObservation.observed_at.desc()).first()
        return deepcopy(row.payload) if row else None

    def view(self, publication_id):
        self.base.publication(publication_id)
        row = self.db.query(EmotionMonitor).filter_by(publication_id=publication_id).first()
        review = self.db.query(EmotionReview).filter_by(publication_id=publication_id).first()
        samples = self.db.query(EmotionObservation).filter_by(monitor_id=row.id).order_by(EmotionObservation.observed_at.desc()).limit(40).all() if row else []
        return {'monitor': {'id':row.id,'status':row.status,'last_sample_at':row.last_sample_at,'last_error':row.last_error} if row else None,
                'latest':deepcopy(samples[0].payload) if samples else None,
                'sample_count':self.db.query(EmotionObservation).filter_by(monitor_id=row.id).count() if row else 0,
                'timeline':[{'id':s.id,'observed_at':s.observed_at,'phase':s.payload['phase'],
                             'states':{x['id']:x['state'] for x in s.payload['evaluations']}} for s in reversed(samples)],
                'review':deepcopy(review.payload) if review else None,
                'auction_source':self.source_config()}

    def create_review(self, body, *, now=None):
        now = now or utc_now()
        old = self.db.query(EmotionRun).filter_by(workspace_id=1, request_key=body.request_key).first()
        if old:return old, False
        pub = self.base.publication(body.publication_id)
        local = now.astimezone(TZ)
        if pub['target_trade_date'] > local.date().isoformat() or (pub['target_trade_date']==local.date().isoformat() and local.time()<time(15,5)):
            raise WorkspaceError('review_before_close')
        existing = self.db.query(EmotionReview).filter_by(publication_id=pub['id']).first()
        if existing:return self.base.get_run(existing.run_id), False
        if self.db.query(EmotionRun).filter(EmotionRun.status.in_(['queued','running'])).first():
            raise WorkspaceError('analysis_running')
        monitor = self.db.query(EmotionMonitor).filter_by(publication_id=pub['id']).first()
        rows = self.db.query(EmotionObservation).filter_by(monitor_id=monitor.id).order_by(EmotionObservation.observed_at).all() if monitor else []
        # Exclude next-session evidence from the original day's frozen review.
        samples = [deepcopy(r.payload) for r in rows if datetime.fromisoformat(r.observed_at).astimezone(TZ).date().isoformat()==pub['target_trade_date']]
        if not samples:
            raise WorkspaceError('review_observations_missing')
        # Keep first/last and every state transition, bounded without claiming the
        # selected set is continuous full tick coverage. Full samples stay in DB.
        chosen, states = {}, {}
        for s in samples:
            current = {x['id']:x['state'] for x in s['evaluations']}
            if current != states:
                chosen[s['id']] = s
            states = current
        chosen[samples[0]['id']] = samples[0]
        chosen[samples[-1]['id']] = samples[-1]
        chosen = sorted(chosen.values(),key=lambda x:x['observed_at'])[-80:]
        ev = [evidence(s['id'],'observation',s['phase']+' / '+s['observed_at'],'panwatch/source_snapshots',s,
                       s['observed_at'],status='sampled') for s in chosen]
        last = samples[-1]
        summary = {'sample_count':len(samples),'selected_count':len(chosen),'first_sample_at':samples[0]['observed_at'],
                   'last_sample_at':last['observed_at'],'states':last['evaluations'],
                   'has_closing_sample':any(s['phase']=='close' and any(q.get('source_time') and
                       datetime.fromisoformat(q['source_time']).astimezone(TZ).time()>=time(15) and
                       q.get('trade_date')==pub['target_trade_date'] for q in s['quotes']) for s in samples),
                   'prospective_plan':datetime.fromisoformat(pub['published_at']).astimezone(TZ) <
                       datetime.combine(datetime.fromisoformat(pub['target_trade_date']).date(),time(9,15),TZ),
                   'coverage_note':'Discrete samples, not tick-complete observations; missing windows remain unknown.'}
        workspace = self.base.ensure_workspace()
        row = EmotionRun(id=uuid4().hex,workspace_id=1,request_key=body.request_key,status='queued',
            target_trade_date=pub['target_trade_date'],created_at=now.isoformat(),base_revision=workspace.revision,
            input_version=workspace.input_version,inputs={'kind':'postmarket','publication':pub,'summary':summary,
                'evidence':ev,'language':workspace.settings.get('language','zh-CN')},events=[])
        self.db.add(row)
        try:self.db.commit()
        except IntegrityError:
            self.db.rollback();raise WorkspaceError('analysis_running') from None
        return row,True

    def publish_review(self, identity, draft, model_label):
        run = self.base.get_run(identity)
        result = self.db.execute(update(EmotionRun).where(EmotionRun.id==identity,EmotionRun.status=='running')
                                 .values(status='succeeded'))
        if not result.rowcount:
            self.db.rollback();raise WorkspaceError('run_cancelled')
        payload = {'id':uuid4().hex,'publication_id':run.inputs['publication']['id'],'run_id':identity,
                   'target_trade_date':run.target_trade_date,'published_at':utc_now().isoformat(),
                   'model_label':model_label,'analysis':draft,'summary':run.inputs['summary'],
                   'evidence':run.inputs['evidence'],'kind':'postmarket'}
        self.db.add(EmotionReview(id=payload['id'],publication_id=payload['publication_id'],run_id=identity,
                                 target_trade_date=run.target_trade_date,published_at=payload['published_at'],payload=payload))
        run.model_label=model_label;run.finished_at=payload['published_at']
        self.db.commit()
        return payload

    def review_memory(self):
        rows = self.db.query(EmotionReview).order_by(EmotionReview.published_at.desc()).limit(7).all()
        return [{'review_id':r.id,'publication_id':r.publication_id,'target_trade_date':r.target_trade_date,
                 'published_at':r.published_at,'memory_summary':r.payload['analysis']['memory_summary'],
                 'open_questions':r.payload['analysis']['open_questions'],'next_day_focus':r.payload['analysis']['next_day_focus'],
                 'observation_summary':r.payload['summary']} for r in rows]
