"""Latest-session collection, skill enforcement and chart contract; synthetic data."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from pan_agent import EventType
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from marketdata.short_term import TZ
from src.modules.administration import builtin_skills
from src.modules.short_term.overview_facts import collect_overview, unpack
from src.modules.short_term.overview_agent import validate_overview, run_overview
from src.modules.short_term.overview_repository import OverviewRepository, SKILL_ID
from src.modules.short_term.overview_schema import OverviewRefresh, StagePosition
from src.modules.short_term.repository import EmotionRepository, WorkspaceError
from src.platform.persistence.database import Base
from src.platform.persistence.models import MCPConnection, EmotionOverview, EmotionRun, EmotionWorkspace

NOW = datetime(2026, 11, 15, 12, tzinfo=TZ)


@pytest.fixture(autouse=True)
def no_network_pacing(monkeypatch):
    monkeypatch.setattr('src.modules.short_term.overview_facts.REQUEST_INTERVAL', 0)


def test_upstream_rate_limit_is_retried_without_losing_directory_coverage():
    original, calls = provider()
    attempts = 0
    async def query(tool, args):
        nonlocal attempts
        if tool == 'screener_search':
            attempts += 1
            if attempts == 1:
                return {'isError': True, 'content': [{'type': 'text', 'text': json.dumps({'error_code': 429002})}]}
        return await original(tool, args)
    facts = asyncio.run(collect_overview(query, now=NOW))
    assert attempts == 2
    assert facts['coverage']['status'] == 'complete'
    assert any(c['status'] == 'rate_limited' for c in facts['raw']['calls'])


def provider(*, missing=False, duplicate=False, late=False):
    calls = []
    async def query(tool, args):
        calls.append((tool, args))
        if tool == 'trading_days':
            data = {'trade_days': ['2026-11-12', '2026-11-13', '2026-11-16']}
        elif tool == 'screener_search':
            data = {'total': 4, 'items': [{'symbol': s, 'name': n} for s, n in [('600000.SH', 'A'), ('300001.SZ', 'B'), ('688001.SH', 'C'), ('002001.SZ', 'ST D')]]}
            if duplicate: data['items'][-1] = data['items'][0]
        elif tool == 'quote':
            data = [{'symbol': s, 'last_done': '11', 'prev_close': '10', 'turnover': '100000', 'trade_status': 'Normal',
                     'timestamp': ('2026-11-12' if late else '2026-11-13') + 'T15:00:00+08:00'} for s in args['symbols']]
            if missing: data = data[:-1]
        elif tool == 'market_temperature':
            data = {'temperature': 98, 'timestamp': '2026-11-13T21:00:00+08:00'}
        else:
            data = {'list': []}
        return {'content': [{'type': 'text', 'text': json.dumps(data)}]}
    return query, calls


def collect(**kwargs):
    query, calls = provider(**kwargs)
    return asyncio.run(collect_overview(query, now=NOW)), calls


def analysis():
    claim = {'text': 'Synthetic observation.', 'evidence_ids': ['overview:breadth']}
    axis = {'state': 'insufficient', 'explanation': 'No preceding completed snapshot.', 'evidence_ids': ['overview:comparison']}
    return {'title': 'Test market view', 'summary': 'Observed breadth, with missing limit data.', 'direction': 'insufficient', 'direction_reason': 'Need comparison.',
        'stage': {'kind': 'between', 'stages': ['repair', 'expansion'], 'status': 'candidate', 'rationale': 'Boundary uncertain.', 'evidence_ids': ['overview:breadth']},
        'loss_relief': axis, 'profit_diffusion': axis,
        'groups': [{'group': g, 'status': status, 'explanation': 'Synthetic evidence.', 'evidence_ids': ['overview:breadth']} for g, status in [('G','observed'),('A','proxy'),('P','missing'),('R','observed')]],
        'supports': [claim], 'counters': [claim], 'next_checks': [{'window':'Next session','observe':'Breadth','strengthens':'Expansion','invalidates':'Weakness'}], 'limitations':['No limit-event data.']}


def test_latest_session_uses_calendar_and_quotes_not_vendor_temperature_phase():
    facts, calls = collect()
    assert facts['trade_date'] == '2026-11-13'
    assert facts['refresh_after'] == '2026-11-16T09:31:00+08:00'
    assert facts['coverage']['excluded_st'] == 1
    assert facts['coverage']['valid'] == 3
    assert facts['metrics']['breadth']['rising'] == 3
    assert facts['metrics']['boards'][-1]['median'] is None
    assert facts['metrics']['limit_up'] is None
    assert facts['metrics']['feedback']['status'] == 'missing'
    assert facts['temperature']['temperature'] == 98
    assert 'stage' not in facts  # A vendor reading must not force an overheat classification.
    assert {c[0] for c in calls} <= {'trading_days','quote','screener_search','market_temperature','history_market_temperature'}


def test_missing_duplicate_and_stale_inputs_do_not_become_complete_breadth():
    for variant in ({'missing': True}, {'duplicate': True}):
        facts, _ = collect(**variant)
        assert facts['coverage']['status'] == 'partial'
    with pytest.raises(ValueError, match='market_data_stale'):
        collect(late=True)


def test_position_contract_rejects_fabricated_precision_and_nonadjacent_ranges():
    for value in [dict(kind='between', stages=['ice','heat'], status='candidate', rationale='x', evidence_ids=['x']),
                  dict(kind='stage', stages=['repair'], status='supported', rationale='x', evidence_ids=['x'], progress=.7)]:
        with pytest.raises(ValueError): StagePosition.model_validate(value)
    assert StagePosition(kind='between', stages=['retreat','ice'], status='candidate', rationale='x', evidence_ids=['x'])
    assert StagePosition(kind='unknown', stages=[], status='insufficient', rationale='x', evidence_ids=[])


def test_validation_requires_proxies_missing_data_and_comparison_to_remain_explicit():
    facts, _ = collect()
    assert validate_overview(analysis(), facts).stage.kind == 'between'
    for mutate in [lambda d: d['supports'][0].update(evidence_ids=['invented']),
                   lambda d: d['stage'].update(status='supported'),
                   lambda d: d.update(direction='improving'),
                   lambda d: d['groups'][2].update(status='observed')]:
        draft = deepcopy(analysis()); mutate(draft)
        with pytest.raises(ValueError): validate_overview(draft, facts)


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/overview.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(MCPConnection(provider='longbridge', enabled=True, credentials='test-only', checked_at=1,
            tools=json.dumps([{'name': t} for t in ['trading_days','screener_search','quote','market_temperature']])))
        db.commit()
    yield factory
    engine.dispose()


def test_latest_read_cache_idempotency_disabled_skill_and_old_result_preservation(sessions):
    facts, _ = collect()
    with sessions() as db:
        repo = OverviewRepository(db)
        assert repo.view(NOW)['overview'] is None
        body = OverviewRefresh(request_key='overview-test-1')
        run, created = repo.create(body, NOW)
        assert created
        assert repo.create(body, NOW)[0].id == run.id
        EmotionRepository(db).claim_run(run.id)
        repo.publish(run.id, facts, analysis(), 'synthetic')
        assert repo.view(NOW)['overview']['trade_date'] == '2026-11-13'
        assert repo.create(OverviewRefresh(request_key='overview-test-2'), NOW) == (None, False)
        row = db.get(EmotionOverview, 1)
        old = deepcopy(row.payload)
        next_run, _ = repo.create(OverviewRefresh(request_key='overview-test-3', force=True), NOW)
        EmotionRepository(db).finish_failed(next_run.id, 'synthetic_failure')
        assert db.get(EmotionOverview, 1).payload == old
        builtin_skills.configure(db, False, SKILL_ID)
        with pytest.raises(WorkspaceError, match='overview_skill_unavailable'):
            repo.create(OverviewRefresh(request_key='overview-test-4', force=True), NOW)
        assert db.get(EmotionOverview, 1).payload == old


@pytest.mark.parametrize('change', ['cancel', 'inputs'])
def test_cancelled_or_outdated_run_cannot_replace_latest_overview(sessions, change):
    facts, _ = collect()
    with sessions() as db:
        repo = OverviewRepository(db)
        run, _ = repo.create(OverviewRefresh(request_key='publication-guard'), NOW)
        EmotionRepository(db).claim_run(run.id)
        if change == 'cancel':
            run.status = 'cancelled'
        else:
            db.get(EmotionWorkspace, 1).input_version += 1
        db.commit()
        with pytest.raises(WorkspaceError):
            repo.publish(run.id, facts, analysis(), 'synthetic')
        assert db.get(EmotionOverview, 1) is None
        assert db.get(EmotionRun, run.id).status != 'succeeded'


def test_runtime_actually_loads_installed_skill_before_validating():
    facts, _ = collect()
    class Model:
        turn = 0
        async def chat_stream(self, messages, **kwargs):
            self.turn += 1
            names = {s['function']['name'] for s in kwargs['tools']}
            assert names == {'load_builtin_skill','get_market_facts','validate_overview'}
            if self.turn == 1: calls = [('load_builtin_skill', {})]
            elif self.turn == 2:
                assert 'PanWatch 总览契约' in str(messages)
                calls = [('get_market_facts', {})]
            else: calls = [('validate_overview', analysis())]
            yield 'message', {'content':'','tool_calls':[{'id':str(self.turn),'name':n,'arguments':json.dumps(a)} for n,a in calls]}
    events = []
    class Sink:
        async def publish(self,event): events.append(event)
    async def check(): pass
    result = asyncio.run(run_overview(Model(),SimpleNamespace(id='test',inputs={'language':'zh-CN'}), facts,Sink(),check))
    assert result['stage']['stages'] == ['repair','expansion']
    assert any(e.type == EventType.TOOL_COMPLETED and e.data.get('tool') == 'load_builtin_skill' for e in events)


def test_truncated_mcp_results_are_rejected_even_if_json_is_parseable():
    with pytest.raises(ValueError, match='truncated'):
        unpack({'content': [{'type':'text','text':'[TRUNCATED partial response]'}, {'type':'text','text':'{"total":100,"items":[]}'}]})
    with pytest.raises(ValueError, match='truncated'):
        unpack({'structuredContent': {'_truncated': {'cuts': ['items']}, 'items': []}})
