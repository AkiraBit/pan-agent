"""Frozen conditions, portable output and supplementary-source boundaries."""
import asyncio
from copy import deepcopy
import json
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.modules.short_term.overview_reporting import engine
from src.modules.short_term.overview_supplement import supplement
from src.modules.short_term.overview_repository import OverviewRepository
from src.modules.short_term.overview_schema import OverviewRefresh
from src.modules.short_term.overview_agent import validate_overview
from src.modules.short_term.repository import EmotionRepository
from src.modules.short_term.workspace_api import router
from src.platform.persistence.database import get_db
from src.platform.persistence.models import EmotionRun
from src.web.response import ResponseWrapperMiddleware
from test_sentiment_overview import collect, analysis, sessions, no_network_pacing, NOW


def payload():
    facts, _ = collect()
    facts.update(run_id='run-one', analyzed_at='2026-11-15T12:00:00+08:00', analysis=analysis())
    return facts


def registered():
    p = payload()
    p['analysis']['next_checks'][0]['rule'] = {'metric':'positive_ratio','operator':'gte','value':.6,'basis':'test-only','calibration':'unvalidated'}
    p['report'] = engine().enrich_report(p)
    return p


def next_day(p):
    f = deepcopy(p)
    f.update(trade_date='2026-11-16', as_of='2026-11-16T15:00:00+08:00', collected_at='2026-11-16T15:01:00+08:00', intraday=False)
    return f


def test_frozen_conditions_mature_on_the_registered_day_without_hindsight():
    p = registered(); f = next_day(p)
    checks = engine().continuity(p, f)['checks']
    assert checks[0]['state'] == 'met'
    # Same-session refresh cannot rewrite yesterday's threshold.
    f['analysis']['next_checks'][0]['rule']['value'] = .99
    f['report'] = engine().enrich_report(f, p)
    f['metrics']['breadth']['positive_ratio'] = .7
    again = engine().continuity(f, f)['checks'][0]
    assert again['rule']['value'] == .6 and again['state'] == 'met'
    assert p['report']['registered_checks'][0]['rule']['value'] == .6
    for update, state in [({'intraday':True},'waiting'), ({'universe_hash':'changed'},'insufficient'),
                           ({'trade_date':'2026-11-17'},'expired')]:
        changed = {**next_day(p), **update}
        assert engine().continuity(p,changed)['checks'][0]['state'] == state


def test_invalidation_wins_and_missing_or_prose_never_becomes_passed():
    p=registered(); f=next_day(p)
    c=p['report']['registered_checks'][0]
    c['invalidation_rule']={**c['rule'],'metric':'p10','value':20,'operator':'lt'}
    assert engine().evaluate_check(c,f)['state']=='invalidated'
    f['metrics']['breadth']['p10']=None
    assert engine().evaluate_check(c,f)['state']=='insufficient'
    c['rule']=None
    assert engine().evaluate_check(c,f)['state']=='review_required'


def test_proxy_feedback_cannot_be_promoted_to_observed_and_numeric_windows_are_explicit():
    f=payload(); f['metrics']['feedback']['status']='proxy'
    draft=analysis();draft['groups'][2]['status']='observed'
    with pytest.raises(ValueError,match='P remains'):
        validate_overview(draft,f)
    draft=analysis();draft['next_checks'][0]['rule']={'metric':'positive_ratio','operator':'gt','value':.5,'basis':'test','calibration':'unvalidated'}
    with pytest.raises(ValueError,match='verification_window'):
        validate_overview(draft,f)
    draft['next_checks'][0]['verification_window']='next_session_close'
    assert validate_overview(draft,f)


def test_observed_attack_can_cite_host_calculated_exact_cohort_promotion():
    f = payload()
    f['supplement'] = {'statistics': {'status': 'available'},
                       'pools': {k: {'status': 'available'} for k in ('up', 'down', 'broken')}}
    f['evidence'].append({'id': 'overview:context-promotions'})
    draft = analysis()
    draft['groups'][1].update(status='observed', evidence_ids=['overview:context-promotions'])
    assert validate_overview(draft, f)
    f['supplement']['pools']['up']['status'] = 'partial'
    with pytest.raises(ValueError, match='exact limit events are unavailable'):
        validate_overview(draft, f)


def test_renderer_and_cli_preserve_chinese_content_and_escape_injection(tmp_path):
    p=registered(); p.pop('raw',None)
    p['analysis']['title']='复盘 <script>alert(1)</script>'
    p['analysis']['summary']='引用 </style><img src=x onerror=alert(1)>'
    rendered=engine().render_html(p)
    assert '<script>alert' not in rendered and '<img src=x' not in rendered
    assert '&lt;script&gt;' in rendered and 'Content-Security-Policy' in rendered
    source=tmp_path/'input.json'; target=tmp_path/'report.html'
    source.write_text(json.dumps(p,ensure_ascii=False))
    subprocess.run([sys.executable,engine().__file__,'--input',str(source),'--output',str(target)],check=True)
    assert target.read_text()==rendered


def test_published_runs_are_immutable_and_export_matches_that_run(sessions):
    facts,_=collect()
    with sessions() as db:
        repo=OverviewRepository(db)
        run,_=repo.create(OverviewRefresh(request_key='first-report'),NOW)
        EmotionRepository(db).claim_run(run.id)
        first=repo.publish(run.id,facts,analysis(),'test')
        run2,_=repo.create(OverviewRefresh(request_key='second-report',force=True),NOW)
        EmotionRepository(db).claim_run(run2.id)
        changed=analysis();changed['title']='Revised'
        repo.publish(run2.id,facts,changed,'test')
        assert db.get(EmotionRun,run.id).inputs['published_overview']==first
        app=FastAPI();app.include_router(router,prefix='/api/short-term');app.add_middleware(ResponseWrapperMiddleware)
        app.dependency_overrides[get_db]=lambda: db
        with TestClient(app) as client:
            response=client.get('/api/short-term/sentiment-overview/report',params={'format':'json','run_id':run.id})
            assert response.json()==first  # No API transport wrapper in the downloadable JSON.
            html=client.get('/api/short-term/sentiment-overview/report',params={'run_id':run.id})
            assert html.status_code==200 and first['analysis']['title'] in html.text
            assert 'attachment' in html.headers['content-disposition']
            assert client.get('/api/short-term/sentiment-overview/report?format=exe').status_code==400


@pytest.mark.parametrize('wrong_day,bad_count',[(False,False),(True,False),(False,True)])
def test_supplement_keeps_vendor_denominators_and_rejects_invalid_dates(wrong_day,bad_count):
    f=payload()
    async def fetch(op,args):
        source_time = 1794499200000
        if op.endswith('statistics'):
            return {'timestamp':source_time,'trade_date':'2026-11-12' if wrong_day else f['trade_date'],'seal_rate':.5,
                    'limit_up_stock_count':2 if bad_count else 1,'open_stock_count':1,'touched_limit_up_stock_count':2}
        if op.endswith('dragon_tiger_list'):
            return {'timestamp':source_time,'trade_date':f['trade_date'],'stock_items':[{'thscode':'600000.SH','range_days':1},{'thscode':'600000.SH','range_days':3}]}
        return {'timestamp':source_time,'pagination':{'total':2,'page':1},'item':[
            {'thscode':'600000.SH','is_st':False,'is_new':False,'continue_day_cnt':2},
            {'thscode':'600001.SH','is_st':True,'is_new':False,'continue_day_cnt':8}]}
    result=asyncio.run(supplement(f,fetch))['supplement']
    assert result['statistics']['status']==('conflicted' if wrong_day or bad_count else 'available')
    assert result['ladders'][0]['highest']==2
    assert result['ladders'][0]['excluded_or_unknown']==1
    assert len(result['dragon_tiger']['data']['stock_items'])==2


def test_supplement_outage_keeps_the_basic_market_analysis():
    f=payload();before=deepcopy(f['metrics'])
    async def unavailable(*args): raise RuntimeError('not configured')
    result=asyncio.run(supplement(f,unavailable))
    assert result['metrics']==before
    assert result['supplement']['statistics']['status']=='missing'
    assert all(a['status']=='unavailable' for a in result['supplement']['audit'])
