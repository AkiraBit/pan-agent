"""Controlled-clock lifecycle and protocol tests; not live market acceptance."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect
from test_emotion_workbench import (sessions, run_async, fact_fixture, draft_fixture, create,
                                   ScriptedTransport, SYMBOL, NOW)
from src.modules.short_term.abnormal import reference_windows, profile
from src.modules.short_term.auction import read_auction
from src.modules.short_term.disclosures import official_url, relevant_excerpt
from src.modules.short_term.lifecycle_repository import LifecycleRepository
from src.modules.short_term.monitoring import monitor_once
from src.modules.short_term.repository import EmotionRepository, WorkspaceError
from src.modules.short_term.review_agent import validate_review
from src.modules.short_term.schemas import ReviewCreate, WorkspaceSettings
from src.modules.short_term.service import EmotionRunner
from src.modules.short_term.verification import evaluate_conditions, sample_phase
from marketdata.short_term import TZ
from src.platform.scheduling.trading_calendar import is_trading_day


def plan():
    d = draft_fixture()
    d['conditions'] = [dict(d['conditions'][2],rule={'checks':[{'symbol':SYMBOL,'metric':'price','operator':'gte','value':10}],
        'invalidation_checks':[{'symbol':SYMBOL,'metric':'price','operator':'lte','value':8}],
        'mode':'all','persistence_seconds':60})]
    return {'target_trade_date':'2026-11-16','analysis':d}


def sample(clock,price=11,stamp=None):
    return {'id':'obs:test-'+str(clock.second),'observed_at':clock.isoformat(),'phase':sample_phase(clock),
        'quotes':[{'symbol':SYMBOL,'price':price,'source_time':(stamp or clock).isoformat(),'trade_date':clock.date().isoformat()}],
        'auction':{'status':'not_configured','quotes':[]}}


def test_persistence_source_time_gap_and_latched_invalidation():
    p=plan();now=NOW.replace(hour=9,minute=30,second=0)
    first=evaluate_conditions(p,sample(now));assert first[0]['state']=='observing'
    duplicate=evaluate_conditions(p,sample(now+timedelta(seconds=30),stamp=now),first)
    assert duplicate[0]['observations']==1
    second=evaluate_conditions(p,sample(now+timedelta(seconds=30)),first)
    third=evaluate_conditions(p,sample(now+timedelta(seconds=60)),second)
    assert third[0]['state']=='met'
    gap=evaluate_conditions(p,sample(now+timedelta(seconds=200)),third)
    assert gap[0]['state']=='observing' and gap[0]['observations']==1
    invalid=evaluate_conditions(p,sample(now+timedelta(seconds=230),7),gap)
    assert invalid[0]['state']=='invalidated'
    assert evaluate_conditions(p,sample(now+timedelta(seconds=260),11),invalid)[0]['state']=='invalidated'
    assert evaluate_conditions(p,sample(now+timedelta(seconds=300),stamp=now),first)[0]['state']=='unknown'


@pytest.mark.parametrize('clock,expected', [('2026-11-14T09:20:00+08:00','closed'),('2026-11-16T09:20:00+08:00','auction'),('2026-11-16T12:00:00+08:00','closed'),('2026-11-16T15:02:00+08:00','close'),('2026-11-16T15:06:00+08:00','closed')])
def test_session_clock(clock,expected):
    assert sample_phase(datetime.fromisoformat(clock))==expected


def test_auction_never_uses_regular_quote_as_indicative_observation():
    p=plan();p['analysis']['conditions'][0]['window']='auction'
    now=NOW.replace(hour=9,minute=20)
    assert evaluate_conditions(p,sample(now))[0]['state']=='unknown'


def test_abnormal_compounds_returns_and_requires_every_session():
    dates=[];day=NOW.date()
    while len(dates)<31:
        if is_trading_day('CN',day):dates.append(day.isoformat())
        day-=timedelta(days=1)
    dates.reverse()
    stock={'rows':[{'date':d,'close':100*1.1**i} for i,d in enumerate(dates)],'adjustment':'qfq'}
    bench={'rows':[{'date':d,'close':100} for d in dates]}
    result=reference_windows(SYMBOL,stock,bench,dates[-1])
    assert result['windows'][0]['deviation']==pytest.approx(33.1)
    assert result['official_determination']=='unknown' and result['reset_status']=='unverified'
    stock['rows'].pop(-2)
    assert reference_windows(SYMBOL,stock,bench,dates[-1])['windows'][0]['status']=='unavailable'
    assert profile('688001.SH')['benchmark']=='sh000688'
    assert profile('300001.SZ')['ordinary_threshold']==30
    assert profile(SYMBOL)['benchmark']=='sz399107'


def test_rolling_reference_cannot_bypass_missing_adjustment_basis():
    rows={'rows':[{'date':'2026-11-12','close':20},{'date':'2026-11-13','close':10}], 'adjustment':'provider_day'}
    result=reference_windows(SYMBOL,rows,rows,'2026-11-13')
    assert result['status']=='unavailable' and result['windows']==[]
    assert result['reason']=='corporate_action_adjustment_unverified'


def test_primary_identity_and_safe_url():
    assert official_url('https://static.cninfo.com.cn/finalpage/a.PDF')
    assert not official_url('https://static.cninfo.com.cn.evil.test/a.PDF')
    assert not official_url('https://user@www.sse.com.cn/a')
    assert not official_url('https://www.sse.com.cn:bad/a')
    with pytest.raises(ValueError,match='subject_mismatch'): relevant_excerpt('其他公司的异常波动说明','002242','九阳股份')
    assert '重点监控' in relevant_excerpt('九阳股份\n公司被纳入重点监控。','002242','九阳股份')


@run_async
async def test_fuyao_auction_preserves_freshness_and_unknown_direction(monkeypatch):
    from src.platform.marketdata import fuyao_business
    now = NOW.replace(hour=9, minute=20)
    monkeypatch.setattr(fuyao_business, 'providers', lambda kind: ['fuyao'])
    async def fetch(operation, args):
        assert operation == 'get_a_share_auction_snapshot'
        assert args == {'thscodes': SYMBOL, 'stage': 'live'}
        return {'auction_phase': 'live', 'data_status': 'ready', 'timestamp': now.timestamp() * 1000,
                'item': [{'thscode': SYMBOL, 'auction_price': 10, 'pre_close_price': 8,
                          'auction_volume': 200, 'auction_unmatched': 40}]}
    monkeypatch.setattr(fuyao_business, 'fetch', fetch)
    result = await read_auction([SYMBOL], now)
    assert result['status'] == 'available' and result['quotes'][0]['matched_amount_cny'] == 2000
    assert result['quotes'][0]['unmatched_ratio'] is None and result['quotes'][0]['unmatched_side'] == 'unknown'
    assert (await read_auction([SYMBOL], now + timedelta(seconds=16)))['status'] == 'unavailable'
    monkeypatch.setattr(fuyao_business, 'providers', lambda kind: [])
    assert (await read_auction([SYMBOL], now))['status'] == 'not_configured'


class ReviewTransport:
    candidates=[];used_model_label='scripted-review/test-only'
    def __init__(self):self.turn=0
    async def chat_stream(self,messages,**kwargs):
        self.turn+=1
        if self.turn==1:calls=[('read_observations',{})]
        elif self.turn==2:
            data=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
            # ToolResult is serialized by the adapter with a data wrapper.
            data=data.get('data',data)
            ev=data['evidence'][-1]['id']
            draft={'title':'Sampled session review','summary':'Discrete observations, not full tick coverage.',
                'findings':[{'condition_id':c['id'],'assessment':'inconclusive','explanation':'Limited sampling.', 'evidence_ids':[ev]} for c in data['plan']['conditions']],
                'lessons':['Keep missing data unknown.'],'next_day_focus':['Check joint response.'],
                'memory_summary':'Opening samples exist; auction remains unknown.','open_questions':['No licensed auction feed.']}
            calls=[('validate_review',draft)]
        else:calls=[]
        yield 'message',{'content':'' if calls else 'Complete.','model':'scripted','tool_calls':[{'id':f'r{self.turn}-{i}','name':n,'arguments':json.dumps(a)} for i,(n,a) in enumerate(calls)]}


@run_async
async def test_full_lifecycle_persists_review_and_next_day_memory(sessions):
    async def collector(*_):return fact_fixture()
    runner=EmotionRunner(sessions,collector=collector,enricher=None,client_factory=lambda _:ScriptedTransport())
    with sessions() as db:identity=create(EmotionRepository(db)).id
    await runner.execute(identity)
    with sessions() as db:
        repo=EmotionRepository(db);pub=repo.workspace()['publication'];before=deepcopy(pub)
        life=LifecycleRepository(db);life.set_monitor(pub['id'],True,now=NOW)
        assert life.source_config() == {'enabled': False, 'provider_name': 'fuyao'}
    async def auction(*_):return {'status':'not_configured','quotes':[]}
    for clock in [NOW.replace(hour=9,minute=30),NOW.replace(hour=9,minute=31),NOW.replace(hour=15,minute=1)]:
        await monitor_once(runner,clock,quote_reader=lambda _:sample(clock)['quotes'],auction_reader=auction)
        await monitor_once(runner,clock,quote_reader=lambda _:pytest.fail('duplicate slot'),auction_reader=auction)
    with sessions() as db:
        life=LifecycleRepository(db);view=life.view(pub['id']);assert view['sample_count']==3
        with pytest.raises(WorkspaceError,match='before_close'):
            life.create_review(ReviewCreate(request_key='early-review',publication_id=pub['id']),now=NOW)
        row,created=life.create_review(ReviewCreate(request_key='review-run-0001',publication_id=pub['id']),now=NOW.replace(hour=15,minute=10))
        assert created;review_id=row.id
    runner.client_factory=lambda _:ReviewTransport()
    await runner.execute(review_id)
    with sessions() as db:
        repo=EmotionRepository(db);assert repo.get_run(review_id).status=='succeeded',repo.get_run(review_id).error_code
        assert repo.publication(pub['id'])==before
        life=LifecycleRepository(db);review=life.view(pub['id'])['review'];assert review['summary']['has_closing_sample']
        next_run=create(repo,'next-day-review-0002',NOW+timedelta(days=1))
        assert next_run.inputs['reviews'][0]['review_id']==review['id']
        life.recover();assert life.view(pub['id'])['sample_count']==3


def test_migration_141_idempotent(sessions):
    from src.platform.persistence.migrations import _m141_emotion_lifecycle
    with sessions() as db:
        with db.bind.begin() as conn:
            _m141_emotion_lifecycle(conn);_m141_emotion_lifecycle(conn)
            assert 'emotion_observations' in inspect(conn).get_table_names()


def test_model_summary_preserves_original_hash_and_raw_inputs():
    from src.modules.short_term.model_context import agent_facts
    from src.modules.short_term.facts import evidence
    facts=fact_fixture()
    content={'windows':[{'inputs':[{'date':'2026-11-13','stock_close':10}],'deviation':2}],
             'price_basis':{'method':'raw_with_sina_qfq_factors','inputs':[{'date':'2026-11-13','factor':'1','raw_close':10}]}}
    facts['evidence'].append(evidence('abnormal:test','abnormal_calculation','Test','test',content,NOW))
    facts['abnormal']=[content]
    before=deepcopy(facts)
    context=agent_facts(facts)
    assert facts==before and 'abnormal' not in context
    e=context['evidence'][-1]
    assert e['summary']['windows'][0]['archived_input_count']==1 and e['summary']['windows'][0]['deviation']==2
    assert 'content_hash' not in e and e['original_content_hash']==before['evidence'][-1]['content_hash']
    assert e['summary']['price_basis']['archived_input_count']==1 and 'inputs' not in e['summary']['price_basis']
