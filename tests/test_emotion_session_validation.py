"""Controlled-clock runtime acceptance; never labeled a live trading day."""
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import inspect
from test_emotion_workbench import sessions, run_async, fact_fixture, ScriptedTransport, NOW
from test_emotion_lifecycle import sample, ReviewTransport
from src.modules.short_term.session_validation import SessionValidationRepository, phase_coverage, valid_sample
from src.modules.short_term.repository import EmotionRepository, WorkspaceError
from src.modules.short_term.lifecycle_repository import LifecycleRepository
from src.modules.short_term.service import EmotionRunner
from src.modules.short_term.monitoring import monitor_once
from src.modules.short_term.schemas import WorkspaceSettings, RunCreate
from src.platform.persistence.models import EmotionRun, EmotionSessionValidation

DAY='2026-11-16'


def checkpoint(view,name):return next(c for c in view['checkpoints'] if c['id']==name)


def test_repeated_stale_partial_and_sparse_samples_cannot_pass():
    start=NOW.replace(hour=9,minute=30)
    samples=[sample(start+timedelta(seconds=s),stamp=start) for s in range(0,1801,30)]
    result=phase_coverage(samples,DAY,'09:30','10:00',start+timedelta(minutes=31),30)
    assert result['samples']==1 and result['status']=='fail'
    wrong=sample(start,stamp=start-timedelta(days=3));assert not valid_sample(wrong,DAY)
    partial=sample(start);partial['requested_symbols']=['002242.SZ','600825.SH']
    assert not valid_sample(partial,DAY)
    future=sample(start,stamp=start+timedelta(seconds=1));assert not valid_sample(future,DAY)


def test_arm_persists_read_only_view_and_skips_unconfigured_auction(sessions):
    with sessions() as db:
        r=SessionValidationRepository(db)
        with pytest.raises(WorkspaceError,match='calendar'):r.arm('2026-11-15',True,now=NOW-timedelta(days=2))
        view=r.arm(DAY,True,now=NOW-timedelta(days=2))
        assert checkpoint(view,'auction')['status']=='skipped'
        assert not view['natural_session_verified'] and not view['configured_stages_verified']
        before=db.query(EmotionRun).count();r.view(DAY,now=NOW);r.view(DAY,now=NOW)
        assert db.query(EmotionRun).count()==before==0
        assert not r.lifecycle.source_config()['enabled']
        with pytest.raises(WorkspaceError,match='future_premarket'):r.arm(DAY,True,now=NOW.replace(hour=9,minute=15))
        with pytest.raises(WorkspaceError,match='future_premarket'):r.arm(DAY,True,now=NOW.replace(hour=9,minute=10))
    with sessions() as db:
        r=SessionValidationRepository(db)
        assert r.view(DAY,now=NOW)['enabled']
        r.arm(DAY,False,now=NOW)
        assert r.tick(NOW)==[]


def test_queue_is_idempotent_retries_bounded_and_missing_day_fails(sessions):
    with sessions() as db:
        r=SessionValidationRepository(db);r.arm(DAY,True,now=NOW-timedelta(days=2))
        first=r.tick(NOW);assert len(first)==1
        assert r.tick(NOW+timedelta(seconds=30))==[]
        db.get(EmotionRun,first[0]).status='failed';db.commit()
        second=r.tick(NOW+timedelta(minutes=1));assert len(second)==1
        db.get(EmotionRun,second[0]).status='failed';db.commit()
        assert r.tick(NOW+timedelta(minutes=2))==[]
        r.tick(NOW.replace(hour=15,minute=21))
        view=r.view(DAY,now=NOW.replace(hour=15,minute=21))
        assert view['status']=='failed'
        assert checkpoint(view,'premarket')['status']=='fail'
        assert checkpoint(view,'closing')['status']=='fail'
        assert not view['configured_stages_verified']


@run_async
async def test_armed_runtime_full_session_review_and_next_day_memory_survive_restart(sessions,monkeypatch):
    from src.modules.short_term import repository, lifecycle_repository, facts, service, session_validation
    clock=[NOW]
    for module in (repository,lifecycle_repository,facts,service,session_validation):monkeypatch.setattr(module,'utc_now',lambda:clock[0])
    async def collector(*_):
        f=fact_fixture();day='2026-11-13' if clock[0].date()==NOW.date() else DAY
        f['reference_trade_date']=day;f['coverage']={'status':'complete','count':5000,'expected':5000}
        f['collected_at']=clock[0].isoformat();f['quotes'][0].update(trade_date=day,source_time=day+'T15:00:00+08:00')
        return f
    runner=EmotionRunner(sessions,collector=collector,enricher=None,client_factory=lambda _:ScriptedTransport())
    with sessions() as db:
        EmotionRepository(db).save_settings(WorkspaceSettings(monitor_interval_seconds=60,postmarket_enabled=True,postmarket_time='15:05'))
        r=SessionValidationRepository(db);r.arm(DAY,True,now=NOW-timedelta(days=2));identities=r.tick(NOW)
    await runner.execute(identities[0])
    with sessions() as db:
        r=SessionValidationRepository(db);r.tick(NOW+timedelta(minutes=1));view=r.view(DAY,now=NOW+timedelta(minutes=1))
        assert checkpoint(view,'premarket')['status']=='pass'
        assert checkpoint(view,'market_data')['status']=='pass'
        pub=EmotionRepository(db).workspace()['publication'];before=deepcopy(pub)
    async def auction(*_):return {'status':'not_configured','quotes':[]}
    for start,end in [(NOW.replace(hour=9,minute=30),NOW.replace(hour=11,minute=30)),(NOW.replace(hour=13,minute=0),NOW.replace(hour=15,minute=1))]:
        clock[0]=start
        while clock[0]<=end:
            await monitor_once(runner,clock[0],quote_reader=lambda _:sample(clock[0])['quotes'],auction_reader=auction)
            clock[0]+=timedelta(seconds=60)
    clock[0]=NOW.replace(hour=15,minute=5)
    await monitor_once(runner,clock[0],quote_reader=lambda _:sample(clock[0])['quotes'],auction_reader=auction)
    with sessions() as db:
        assert db.query(EmotionRun).count()==1  # Generic review must not race the armed 15:10 review.
    clock[0]=NOW.replace(hour=15,minute=10)
    with sessions() as db:
        r=SessionValidationRepository(db);ids=r.tick(clock[0]);assert len(ids)==1
    runner.client_factory=lambda _:ReviewTransport()
    await runner.execute(ids[0])
    with sessions() as db:
        r=SessionValidationRepository(db);r.tick(clock[0]+timedelta(seconds=30))
        v=r.view(DAY,now=clock[0]+timedelta(seconds=30))
        for key in ('opening','morning','afternoon','closing','postmarket'):assert checkpoint(v,key)['status']=='pass', (key,v)
        review=LifecycleRepository(db).view(pub['id'])['review'];assert review
        assert EmotionRepository(db).publication(pub['id'])==before
    # Reconstruct the runner to prove the next action depends on persisted data.
    clock[0]=NOW+timedelta(days=1)
    runner=EmotionRunner(sessions,collector=collector,enricher=None,client_factory=lambda _:ScriptedTransport())
    with sessions() as db:
        r=SessionValidationRepository(db);ids=r.tick(clock[0]);assert len(ids)==1
        assert db.get(EmotionRun,ids[0]).inputs['reviews'][0]['review_id']==review['id']
    await runner.execute(ids[0])
    with sessions() as db:
        r=SessionValidationRepository(db);r.tick(clock[0]+timedelta(minutes=1));memory_check=checkpoint(r.view(DAY,now=clock[0]),'memory')
        assert memory_check['status']=='pass'
        bound_memory_id=memory_check['publication_id']
        manual,_=EmotionRepository(db).create_run(RunCreate(request_key='later-manual-plan',target_trade_date=clock[0].date()),now=clock[0])
        manual_id=manual.id
    await runner.execute(manual_id)
    with sessions() as db:
        assert EmotionRepository(db).workspace()['publication']['id']!=bound_memory_id
        assert checkpoint(SessionValidationRepository(db).view(DAY,now=clock[0]),'memory')['publication_id']==bound_memory_id
    clock[0]=clock[0].replace(hour=9,minute=30)
    for _ in range(31):
        await monitor_once(runner,clock[0],quote_reader=lambda _:sample(clock[0])['quotes'],auction_reader=auction)
        clock[0]+=timedelta(minutes=1)
    clock[0]=clock[0].replace(hour=10,minute=2)
    with sessions() as db:
        r=SessionValidationRepository(db);r.tick(clock[0]);v=r.view(DAY,now=clock[0])
        assert v['configured_stages_verified'],v
        assert not v['natural_session_verified']  # Auction remains unconfigured.
        assert v['status']=='complete' and not v['enabled']
        assert r.view(DAY,now=clock[0]+timedelta(days=2))['status']=='complete'
        assert not r.lifecycle.source_config()['enabled']


@run_async
async def test_armed_workflow_owns_both_dates_and_generic_schedule_does_not_duplicate(sessions):
    runner=EmotionRunner(sessions)
    with sessions() as db:
        EmotionRepository(db).save_settings(WorkspaceSettings(schedule_enabled=True,schedule_time='08:45'))
        r=SessionValidationRepository(db);r.arm(DAY,True,now=NOW-timedelta(days=2))
        assert r.owns_date(DAY) and r.owns_date('2026-11-17') and not r.owns_date('2026-11-18')
    await runner.schedule_once(NOW)
    await runner.schedule_once(NOW+timedelta(days=1))
    with sessions() as db:assert db.query(EmotionRun).count()==0


@run_async
async def test_scheduler_failure_does_not_skip_later_operations(monkeypatch,sessions):
    import asyncio
    from src.modules.short_term import service
    calls=[];runner=EmotionRunner(sessions)
    async def validation(_):calls.append('validation')
    async def broken():calls.append('generic');raise ValueError('unavailable')
    async def monitor(_):calls.append('monitor')
    async def end(_):raise asyncio.CancelledError()
    monkeypatch.setattr(service,'validation_tick',validation);monkeypatch.setattr(runner,'schedule_once',broken)
    monkeypatch.setattr(service,'monitor_once',monitor);monkeypatch.setattr(service.asyncio,'sleep',end)
    with pytest.raises(asyncio.CancelledError):await runner.schedule_loop()
    assert calls==['validation','generic','monitor']


def test_migration_142_is_additive_and_idempotent(sessions):
    from src.platform.persistence.migrations import _m142_emotion_regulatory_validation
    with sessions() as db:
        with db.bind.begin() as conn:
            _m142_emotion_regulatory_validation(conn);_m142_emotion_regulatory_validation(conn)
            assert {'emotion_regulatory_events','emotion_session_validations'} <= set(inspect(conn).get_table_names())
