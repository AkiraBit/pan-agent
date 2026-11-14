"""An explicitly armed, durable trading-day acceptance run, driven by the service.

No GET performs collection. Checkpoints are computed from persisted evidence,
with future work kept pending and missing auction access explicitly skipped.
"""
from copy import deepcopy
from datetime import datetime, time, timedelta
import math

from marketdata.short_term import TZ
from src.platform.persistence.models import (EmotionSessionValidation, EmotionPublication,
    EmotionMonitor, EmotionObservation, EmotionReview, EmotionRun)
from src.platform.scheduling.trading_calendar import calendar_known, is_trading_day
from .facts import utc_now
from .repository import EmotionRepository, WorkspaceError
from .lifecycle_repository import LifecycleRepository
from .schemas import RunCreate, ReviewCreate
from .verification import next_session

PHASES = [('opening','09:30','10:00'),('morning','10:00','11:30'),('afternoon','13:00','14:57'),('closing','14:57','15:05')]


def stamp(day, clock):
    return datetime.fromisoformat(day+'T'+clock).replace(tzinfo=TZ)


def valid_sample(sample, day, start=None, end=None):
    observed=datetime.fromisoformat(sample['observed_at'])
    fresh=[]
    for q in sample.get('quotes',[]):
        try:
            source=datetime.fromisoformat(q['source_time'])
            tolerance=300 if sample.get('phase')=='close' and source.time()>=time(15) else 90
            if (source.tzinfo and source.astimezone(TZ).date().isoformat()==day and q.get('trade_date')==day
                    and math.isfinite(q.get('price',0)) and 0<q.get('price',0) and 0<=(observed-source).total_seconds()<=tolerance
                    and (not start or source>=start) and (not end or source<=end)):
                fresh.append((q['symbol'],source.isoformat()))
        except (KeyError,TypeError,ValueError):continue
    requested=sample.get('requested_symbols') or [q['symbol'] for q in sample.get('quotes',[])]
    return fresh if requested and len({s for s,_ in fresh} & set(requested))/len(set(requested))>=.8 else []


def phase_coverage(samples, day, start, end, now, interval, *, closing=False):
    a,b=stamp(day,start),stamp(day,end);seen=set();times=[]
    for sample in samples:
        observed=datetime.fromisoformat(sample['observed_at'])
        source_start=stamp(day,'15:00') if closing else a
        signature=tuple(sorted(valid_sample(sample,day,source_start,b)))
        if a<=observed<=min(b,now) and signature and signature not in seen:
            seen.add(signature);times.append(observed)
    times.sort()
    elapsed=max(0,(min(now,b)-a).total_seconds())
    expected=max(1,math.floor(elapsed/interval)+1)
    full_expected=math.floor((b-a).total_seconds()/interval)+1
    ratio=min(1,len(times)/expected)
    edges=[a,*times,min(max(now,a),b)]
    gap=max(((y-x).total_seconds() for x,y in zip(edges,edges[1:])),default=0)
    if closing:full_expected=1;ratio=1 if times else 0;gap=0
    state='pending' if now<a else 'running' if now<=b else 'pass' if ratio>=.8 and gap<=max(90,interval*3) else 'fail'
    reason='source_timed_coverage' if state=='pass' else 'awaiting_window' if state=='pending' else 'coverage_gap' if state=='fail' else 'sampling'
    return {'status':state,'reason':reason,'samples':len(times),'expected':full_expected,
            'coverage':round(ratio,4),'max_gap_seconds':round(gap),'start':a.isoformat(),'end':b.isoformat()}


class SessionValidationRepository:
    def __init__(self, db):
        self.db=db;self.base=EmotionRepository(db);self.lifecycle=LifecycleRepository(db)

    def owns_date(self, day):
        return any(day in {row.trade_date,next_session(row.trade_date)} for row in
                   self.db.query(EmotionSessionValidation).filter_by(enabled=True).all())

    def controlled_publications(self):
        return {row.payload.get('publication_id') for row in
                self.db.query(EmotionSessionValidation).filter_by(enabled=True).all() if row.payload}

    def arm(self, day, enabled, *, now=None):
        now=now or utc_now();target=datetime.fromisoformat(day).date();local=now.astimezone(TZ)
        if enabled and (not calendar_known('CN',target) or not is_trading_day('CN',target) or not next_session(day)):
            raise WorkspaceError('validation_calendar_unavailable')
        if enabled and (target<local.date() or (target==local.date() and local.time()>=time(9,10))):
            raise WorkspaceError('validation_requires_future_premarket')
        if (target-local.date()).days>14:raise WorkspaceError('validation_target_too_far')
        row=self.db.get(EmotionSessionValidation,day)
        if not row:
            row=EmotionSessionValidation(trade_date=day,created_at=now.isoformat(),payload={});self.db.add(row)
        if enabled and (row.payload or {}).get('finished_at'):raise WorkspaceError('validation_already_finished')
        row.enabled=enabled
        payload=deepcopy(row.payload or {});payload.setdefault('monitor_interval_seconds',self.base.workspace()['settings'].get('monitor_interval_seconds',30));payload.setdefault('events',[]).append({'at':now.isoformat(),'type':'armed' if enabled else 'paused'});row.payload=payload
        self.db.commit();return self.view(day,now=now)

    def view(self, day, *, now=None):
        now=(now or utc_now()).astimezone(TZ);row=self.db.get(EmotionSessionValidation,day)
        payload=deepcopy(row.payload or {}) if row else {};following=next_session(day)
        if payload.get('final_view'):
            return {**payload['final_view'],'server_time':now.isoformat(),'enabled':False}
        pubrow=self.db.query(EmotionPublication).filter_by(target_trade_date=day).order_by(EmotionPublication.revision.desc()).first()
        # Bind acceptance to its morning run once one is published, not arbitrary
        # later rewrites which could hide a failed or late premarket publication.
        if payload.get('publication_id'):pubrow=self.db.get(EmotionPublication,payload['publication_id'])
        pub=pubrow.payload if pubrow else None
        monitor=self.db.query(EmotionMonitor).filter_by(publication_id=pubrow.id).first() if pubrow else None
        observations=self.db.query(EmotionObservation).filter_by(monitor_id=monitor.id).order_by(EmotionObservation.observed_at).all() if monitor else []
        samples=[r.payload for r in observations if datetime.fromisoformat(r.observed_at).astimezone(TZ).date().isoformat()==day]
        review=self.db.query(EmotionReview).filter_by(publication_id=pubrow.id).first() if pubrow else None
        source=self.lifecycle.source_config();settings=self.base.workspace()['settings'];interval=payload.get('monitor_interval_seconds',settings.get('monitor_interval_seconds',30))
        checks=[]
        def check(identity,status,reason,**extra):checks.append({'id':identity,'status':status,'reason':reason,**extra})
        known=calendar_known('CN',datetime.fromisoformat(day));opened=is_trading_day('CN',datetime.fromisoformat(day))
        check('calendar','pass' if known and opened else 'fail','confirmed_exchange_session' if known and opened else 'calendar_unavailable')
        heartbeat=datetime.fromisoformat(row.heartbeat_at) if row and row.heartbeat_at else None
        alive=heartbeat and 0<=(now-heartbeat).total_seconds()<90
        check('service','pass' if alive else 'pending' if now<stamp(day,'08:45') else 'fail','heartbeat_current' if alive else 'heartbeat_missing',last_at=row.heartbeat_at if row else None)
        prospective=pub and datetime.fromisoformat(pub['published_at'])<stamp(day,'09:15')
        target_run=self.db.get(EmotionRun,payload.get('premarket_run_id')) if payload.get('premarket_run_id') else None
        check('premarket','pass' if prospective and payload.get('publication_id') else 'pending' if now<stamp(day,'09:15') else 'fail',
              'bound_premarket_publication' if prospective and payload.get('publication_id') else 'awaiting_scheduled_plan',run_status=target_run.status if target_run else None,publication_id=pubrow.id if pubrow else None)
        previous=stamp(day,'00:00').date()-timedelta(days=1)
        while calendar_known('CN',previous) and not is_trading_day('CN',previous):previous-=timedelta(days=1)
        facts=(pub or {}).get('facts',{});coverage=facts.get('coverage',{})
        fresh_reference=facts.get('reference_trade_date')==previous.isoformat() and coverage.get('status')=='complete'
        check('market_data','pass' if payload.get('publication_id') and fresh_reference else 'pending' if now<stamp(day,'09:15') else 'fail',
              'previous_session_complete' if fresh_reference else 'premarket_market_data_incomplete')
        check('auction','skipped' if not source['enabled'] else 'pending' if now<stamp(day,'09:30') else 'pass' if any(s.get('auction',{}).get('status')=='available' for s in samples) else 'fail',
              'auction_not_configured' if not source['enabled'] else 'licensed_source_required')
        for identity,start,end in PHASES:
            checks.append({'id':identity,**phase_coverage(samples,day,start,end,now,interval,closing=identity=='closing')})
        review_on_time=review and datetime.fromisoformat(review.published_at)<=stamp(day,'15:20')
        check('postmarket','pass' if review_on_time else 'fail' if review else 'pending' if now<stamp(day,'15:20') else 'fail','review_persisted' if review_on_time else 'review_late' if review else 'awaiting_review',review_id=review.id if review else None)
        next_pub=self.db.query(EmotionPublication).filter_by(target_trade_date=following).order_by(EmotionPublication.revision.desc()).first() if following else None
        if row:
            next_pub=self.db.get(EmotionPublication,payload['memory_publication_id']) if payload.get('memory_publication_id') else None
        memory=bool(review and next_pub and any(x['review_id']==review.id for x in next_pub.payload.get('review_memory_input',[])))
        memory_on_time=memory and datetime.fromisoformat(next_pub.published_at)<stamp(following,'09:15')
        check('memory','pass' if memory_on_time else 'fail' if memory else 'pending' if following and now<stamp(following,'09:15') else 'fail','next_plan_read_review' if memory_on_time else 'memory_late' if memory else 'awaiting_next_plan',publication_id=next_pub.id if next_pub else None)
        next_samples=[r.payload for r in observations if following and datetime.fromisoformat(r.observed_at).astimezone(TZ).date().isoformat()==following]
        checks.append({'id':'next_open',**phase_coverage(next_samples,following,'09:30','10:00',now,interval)}) if following else check('next_open','fail','calendar_unavailable')
        constraints=[e['content'] for e in (pub or {}).get('facts',{}).get('evidence',[]) if e['kind']=='regulatory_window']
        warnings=sorted(set(['sampling_interval_changed'] if settings.get('monitor_interval_seconds',30)!=interval else []) | set(['auction_not_configured'] if not source['enabled'] else []) | set(['regulatory_source_gaps'] if not constraints or any(c.get('gaps') for c in constraints) else []))
        return {'trade_date':day,'next_trade_date':following,'enabled':bool(row and row.enabled),'server_time':now.isoformat(),
                'heartbeat_at':row.heartbeat_at if row else None,'status':'failed' if any(c['status']=='fail' for c in checks) else 'complete' if all(c['status'] in {'pass','skipped'} for c in checks) else 'armed' if row and row.enabled else 'not_armed',
                'checkpoints':checks,'warnings':warnings,'events':payload.get('events',[])[-60:],'publication_id':pubrow.id if pubrow else None,
                'schedule':{'premarket':'08:45','premarket_deadline':'09:15','postmarket':'15:10','next_memory':'08:45','timezone':'Asia/Shanghai'},
                'rules':{'monitor_interval_seconds':interval,'minimum_quote_coverage':.8,'minimum_sample_coverage':.8,'maximum_gap_seconds':max(90,interval*3)},
                'auction_configured':source['enabled'],'configured_stages_verified':bool(row and all(c['status'] in {'pass','skipped'} for c in checks)),
                'natural_session_verified':bool(row and all(c['status']=='pass' for c in checks))}

    def tick(self, now):
        local=now.astimezone(TZ);start=[]
        rows=self.db.query(EmotionSessionValidation).filter_by(enabled=True).all()
        for row in rows:
            day=row.trade_date;following=next_session(day)
            if not following:continue
            payload=deepcopy(row.payload or {});row.heartbeat_at=now.isoformat()
            if local.date().isoformat() in {day,following} and time(8,45)<=local.time()<time(9,10):
                key='premarket' if local.date().isoformat()==day else 'memory'
                if key=='memory' and not payload.get('review_id'):continue
                existing=self.db.get(EmotionRun,payload.get(key+'_run_id')) if payload.get(key+'_run_id') else None
                attempts=payload.get(key+'_attempts',0)
                if not existing or (existing.status in {'failed','interrupted'} and attempts<2):
                    try:
                        run,created=self.base.create_run(RunCreate(request_key=f'validation:{day}:{key}:{attempts+1}',target_trade_date=local.date()),now=now)
                        payload[key+'_run_id']=run.id;payload[key+'_attempts']=attempts+1
                        if created:start.append(run.id)
                    except WorkspaceError:pass
            pre=self.db.get(EmotionRun,payload.get('premarket_run_id')) if payload.get('premarket_run_id') else None
            if pre and pre.publication_id:
                payload['publication_id']=pre.publication_id
                monitor=self.db.query(EmotionMonitor).filter_by(publication_id=pre.publication_id).first()
                if not monitor:self.lifecycle.set_monitor(pre.publication_id,True,now=now)
            memory=self.db.get(EmotionRun,payload.get('memory_run_id')) if payload.get('memory_run_id') else None
            if memory and memory.publication_id:payload['memory_publication_id']=memory.publication_id
            if payload.get('publication_id') and stamp(day,'15:10')<=local<stamp(following,'08:40'):
                try:
                    existing=self.db.get(EmotionRun,payload.get('review_run_id')) if payload.get('review_run_id') else None
                    attempts=payload.get('review_attempts',0)
                    if not existing or (existing.status in {'failed','interrupted'} and attempts<2):
                        review,created=self.lifecycle.create_review(ReviewCreate(publication_id=payload['publication_id'],request_key=f'validation:{day}:review:{attempts+1}'),now=now)
                        payload['review_run_id']=review.id;payload['review_attempts']=attempts+1
                        if created:start.append(review.id)
                except WorkspaceError:pass
            review=self.db.query(EmotionReview).filter_by(publication_id=payload.get('publication_id')).first()
            if review:payload['review_id']=review.id
            row.payload=payload;self.db.commit()
            view=self.view(day,now=now);states={c['id']:c['status'] for c in view['checkpoints']}
            if states!=payload.get('checkpoint_states'):
                payload['checkpoint_states']=states;payload.setdefault('events',[]).append({'at':now.isoformat(),'type':'checkpoint_transition','states':states});payload['events']=payload['events'][-100:]
            if local>stamp(following,'10:01'):
                row.enabled=False;payload['finished_at']=now.isoformat();payload['final_view']={**view,'enabled':False}
            row.payload=payload;self.db.commit()
        return start


async def validation_tick(runner, now=None):
    now=now or utc_now()
    # The trading sampler runs every five seconds; audit writes need only 30s.
    last=getattr(runner,'validation_checked_at',None)
    if last and 0<=(now-last).total_seconds()<30:return
    runner.validation_checked_at=now
    identities=await runner.write(lambda r: SessionValidationRepository(r.db).tick(now))
    for identity in identities:runner.start(identity)
