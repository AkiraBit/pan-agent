"""Trading-session sampler. GETs never initiate upstream reads or model runs."""
import asyncio
from datetime import datetime, time, timezone
from uuid import uuid4

from marketdata.sentiment import snapshots
from marketdata.short_term import TZ
from .auction import read_auction
from .facts import utc_now
from .lifecycle_repository import LifecycleRepository
from .schemas import ReviewCreate, WorkspaceSettings
from .verification import evaluate_conditions, next_session, sample_phase
from .repository import WorkspaceError, run_dto
from .session_validation import SessionValidationRepository


async def monitor_once(runner, now=None, *, quote_reader=snapshots, auction_reader=read_auction):
    clock = now or utc_now()
    local = clock.astimezone(TZ)
    settings = await asyncio.to_thread(runner.read, lambda r: WorkspaceSettings.model_validate(r.workspace()['settings']))
    active = await asyncio.to_thread(runner.read, lambda r: LifecycleRepository(r.db).active())
    controlled = await asyncio.to_thread(runner.read, lambda r: SessionValidationRepository(r.db).controlled_publications())
    for monitor in active:
        target = monitor['target_trade_date']
        following = next_session(target)
        if not following:
            continue
        if local.date().isoformat() > following or (local.date().isoformat()==following and local.time()>time(10)):
            await runner.write(lambda r: LifecycleRepository(r.db).complete(monitor['id']))
            continue
        if monitor['publication_id'] not in controlled and local.date().isoformat()==target and local.strftime('%H:%M')>=settings.postmarket_time and settings.postmarket_enabled:
            try:
                def review(r):
                    row, created = LifecycleRepository(r.db).create_review(ReviewCreate(
                        request_key='review:'+monitor['publication_id'], publication_id=monitor['publication_id']), now=clock)
                    return run_dto(row), created
                row, created = await runner.write(review)
                if created: runner.start(row['id'])
            except WorkspaceError:
                pass
        phase = sample_phase(clock)
        if phase=='closed' or local.date().isoformat() not in {target, following}:
            continue
        if local.date().isoformat()==following and not time(9,30)<=local.time()<=time(10):
            continue
        interval = 5 if phase=='auction' else settings.monitor_interval_seconds
        slot = str(int(clock.timestamp())//interval)
        token = await runner.write(lambda r: LifecycleRepository(r.db).claim(monitor['id'],clock.astimezone(timezone.utc),slot))
        if not token: continue
        try:
            def inputs(r):
                lifecycle = LifecycleRepository(r.db)
                return r.publication(monitor['publication_id']), lifecycle.latest(monitor['id']), lifecycle.source_config(private=True)
            pub, previous, config = await asyncio.to_thread(runner.read, inputs)
            symbols = [s['symbol'] for s in pub['analysis']['watchlist']]
            rows, auction = await asyncio.wait_for(asyncio.gather(asyncio.to_thread(quote_reader,symbols),
                auction_reader(config,symbols,clock)), 25)
            observed = now or utc_now()
            payload = {'id':'obs:'+uuid4().hex,'observed_at':observed.isoformat(),'phase':phase,
                       'quotes':rows,'auction':auction,'requested_symbols':symbols}
            payload['evaluations'] = evaluate_conditions(pub,payload,(previous or {}).get('evaluations'),
                                                          max_gap_seconds=max(15,interval*2+10))
            await runner.write(lambda r: LifecycleRepository(r.db).save_sample(monitor['id'],token,slot,payload))
        except asyncio.CancelledError:
            await runner.write(lambda r: LifecycleRepository(r.db).release(monitor['id'],token,'worker_stopped'))
            raise
        except Exception:
            await runner.write(lambda r: LifecycleRepository(r.db).release(monitor['id'],token,'sampling_failed'))
