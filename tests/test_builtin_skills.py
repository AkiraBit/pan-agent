"""Skill settings and the production assistant runtime, with a synthetic broker/model."""
import asyncio
import json

from pan_agent import ModelMessage, RunRequest, RunStatus
from sqlalchemy.orm import Session

from test_builtin_mcp import setup, finish, PREFIX  # noqa: F401 - shared isolated protocol fixture
from src.modules.administration import builtin_skills as skills
from src.modules.assistant.repository import AssistantRepository
from src.modules.assistant.service import AssistantService
from src.modules.assistant.task_runner import DurableRuntimeEventSink
from src.modules.assistant.tools import build_panwatch_tool_registry
from src.platform.persistence.models import AppSettings

BASE = '/api/builtin-skills'


def test_shipped_catalog_and_dependency_states_do_not_grant_or_revoke_authorization(setup):
    client, engine, provider, _ = setup
    item = client.get(BASE).json()['data']['items'][0]
    assert item['id'] == 'longbridge' and not item['enabled'] and not item['available']
    assert item['connection_status'] == 'authorization_required'
    assert item['source_url'].endswith(skills.UPSTREAM_REVISION + '/skills/longbridge/SKILL.md')
    assert len(item['tools']) == 7
    assert client.put(BASE + '/longbridge', json={'enabled': True}).status_code == 200
    assert not provider.calls  # Enabling only stores a preference.
    finish(client)
    assert client.get(BASE).json()['data']['items'][0]['connection_status'] == 'test_required'
    client.post(PREFIX + '/test')
    assert client.get(BASE).json()['data']['items'][0]['connection_status'] == 'mcp_disabled'
    client.put(PREFIX, json={'enabled': True})
    assert client.get(BASE).json()['data']['items'][0]['available']
    provider.calls.clear()
    disabled = client.put(BASE + '/longbridge', json={'enabled': False}).json()['data']
    assert not disabled['available'] and disabled['connection_status'] == 'ready'
    assert not provider.calls
    connection = client.get('/api/mcp-connections').json()['data']['items'][0]
    assert connection['authorized'] and connection['enabled']
    with Session(engine) as db:
        assert not skills.status(db)['enabled']  # Reload through a fresh session.


def test_skill_settings_require_login_and_cannot_install_custom_skills(setup):
    client, _, provider, _ = setup
    assert client.post(BASE, json={'url': 'https://example.org/SKILL.md'}).status_code == 405
    assert client.put(BASE + '/custom', json={'enabled': True}).status_code == 404
    for body in [{'enabled': 'true'}, {'enabled': True, 'command': 'npx'}, {'enabled': True, 'content': 'injected'}]:
        assert client.put(BASE + '/longbridge', json=body).status_code == 422
    client.headers.pop('Authorization')
    assert client.get(BASE).status_code == 401
    assert client.put(BASE + '/longbridge', json={'enabled': True}).status_code == 401
    assert not provider.calls


def test_disabled_skill_is_not_exposed_and_live_disable_or_disconnect_blocks_stale_registry(setup):
    client, engine, _, _ = setup
    finish(client); client.post(PREFIX + '/test'); client.put(PREFIX, json={'enabled': True})
    client.put(BASE + '/analyze-a-share-sentiment', json={'enabled': False})
    request = RunRequest(run_id='skill-test', messages=[ModelMessage(role='user', content='用长桥查报价')])
    with Session(engine) as db:
        assert 'load_builtin_skill' not in {t.name for t in build_panwatch_tool_registry(db).registered_tools()}
    client.put(BASE + '/longbridge', json={'enabled': True})
    with Session(engine) as db:
        registry = build_panwatch_tool_registry(db)
        result = asyncio.run(registry.execute('load_builtin_skill', request, {'skill_id': 'longbridge'}))
        assert result.ok and 'longbridge_quote' in result.summary
        assert result.data['upstream_revision'] == skills.UPSTREAM_REVISION
        assert 'PRIVATE' not in result.model_dump_json()
        assert not asyncio.run(registry.execute('load_builtin_skill', request, {'skill_id': '../../secret'})).ok
        client.put(BASE + '/longbridge', json={'enabled': False})
        assert not asyncio.run(registry.execute('load_builtin_skill', request, {'skill_id': 'longbridge'})).ok
        client.put(BASE + '/longbridge', json={'enabled': True})
        client.delete(PREFIX)
        assert not asyncio.run(registry.execute('load_builtin_skill', request, {'skill_id': 'longbridge'})).ok


def test_repeated_skill_preferences_persist_one_setting_without_changing_other_settings(setup):
    client, engine, _, _ = setup
    with Session(engine) as db:
        db.add(AppSettings(key='unrelated', value='preserve')); db.commit()
    for enabled in [True, False, True]:
        assert client.put(BASE + '/longbridge', json={'enabled': enabled}).status_code == 200
    with Session(engine) as db:
        assert db.query(AppSettings).filter_by(key=skills.SETTING_KEY).count() == 1
        assert skills.status(db)['enabled']
        assert db.query(AppSettings).filter_by(key='unrelated').one().value == 'preserve'


def test_production_runtime_loads_skill_then_calls_longbridge_and_records_both(setup):
    client, engine, _, _ = setup
    finish(client); client.post(PREFIX + '/test'); client.put(PREFIX, json={'enabled': True})
    client.put(BASE + '/longbridge', json={'enabled': True})

    class ScriptedModel:
        model = 'scripted-builtin-skill-contract'
        step = 0

        async def chat_stream(self, messages, **kwargs):
            exposed = {item['function']['name'] for item in kwargs.get('tools', [])}
            assert {'load_builtin_skill', 'longbridge_quote'} <= exposed
            self.step += 1
            calls = []
            if self.step == 1:
                calls = [{'id': 'skill-load', 'name': 'load_builtin_skill', 'arguments': json.dumps({'skill_id': 'longbridge'})}]
            elif self.step == 2:
                assert any('Supported MCP mapping' in str(m) for m in messages)
                calls = [{'id': 'quote', 'name': 'longbridge_quote', 'arguments': '{}'}]
            yield 'message', {'content': 'Synthetic quote: 100' if self.step == 3 else '', 'model': self.model,
                              'tool_calls': calls, 'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}

    with Session(engine) as db:
        repo = AssistantRepository(db)
        conversation = repo.create_conversation(stock_symbol=None, stock_market=None, initial_context=None)
        task = repo.create_task(conversation_id=conversation.id, user_message_id=None, context={})
        repo.claim_task(task.id)
        service = AssistantService(repo)
        sink = DurableRuntimeEventSink(service, task.id)
        request = RunRequest(run_id=str(task.id), messages=[ModelMessage(role='user', content='用长桥技能查询报价')])
        async def run():
            result = await service.build_runtime(ScriptedModel()).run(request, sink)
            await sink.flush()
            return result
        result = asyncio.run(run())
        assert result.status is RunStatus.COMPLETED, result.error_code
        calls = repo.list_task_tool_invocations(task.id)
        loaded = next(c for c in calls if c.tool_name == 'load_builtin_skill')
        assert loaded.result_data['skill_id'] == 'longbridge'
        assert loaded.result_data['version'] == skills.VERSION
        assert any(c.tool_name == 'longbridge_quote' for c in calls)


def test_all_thirteen_sources_are_pinned_and_unsupported_skills_cannot_be_enabled(setup):
    client, engine, provider, _ = setup
    items = [item for item in client.get(BASE).json()['data']['items'] if item.get('provider') != 'panwatch']
    assert len(items) == 13
    assert sum(item['support'] == 'partial' for item in items) == 5
    assert skills.upstream()['revision'] == skills.UPSTREAM_REVISION
    source_ids = {path.split('/')[0] for path in skills.upstream()['files'] if path.endswith('/SKILL.md')}
    assert source_ids == {item['id'] for item in items}
    for item in items:
        response = client.get(BASE + '/' + item['id'] + '/source')
        assert response.status_code == 200
        source = response.json()['data']
        assert source['content'] == skills.upstream()['files'][item['id'] + '/SKILL.md']
        assert source['bundled_file_count'] > 0
        if item['support'] == 'unsupported':
            assert not item['available'] and not item['enabled'] and item['version'] is None
            assert client.put(BASE + '/' + item['id'], json={'enabled': True}).status_code == 409
    assert client.get(BASE + '/custom/source').status_code == 404
    with Session(engine) as db:
        assert db.query(AppSettings).filter(AppSettings.key.like('builtin_skill.%')).count() == 0
    assert not provider.calls
    client.headers.pop('Authorization')
    assert client.get(BASE + '/longbridge/source').status_code == 401


def test_independent_skill_settings_and_actual_discovered_tool_requirements(setup):
    client, engine, provider, _ = setup
    finish(client)
    # A provider can return only a subset of the built-in allowlist.
    provider.tools = [tool for tool in provider.tools if tool['name'] == 'quote']
    client.post(PREFIX + '/test'); client.put(PREFIX, json={'enabled': True})
    for skill_id in ('longbridge-market-data', 'longbridge-technical', 'longbridge-portfolio'):
        assert client.put(BASE + '/' + skill_id, json={'enabled': True}).status_code == 200
    items = {item['id']: item for item in client.get(BASE).json()['data']['items']}
    assert not items['longbridge']['enabled']
    # Quotes remain usable, while unavailable workflows are individually marked.
    assert items['longbridge-market-data']['available']
    assert any(not feature['tools_present'] for feature in items['longbridge-market-data']['capabilities'])
    assert items['longbridge-technical']['enabled'] and not items['longbridge-technical']['available']
    assert items['longbridge-portfolio']['connection_status'] == 'tools_missing'
    provider.tools += [{'name': 'candlesticks', 'inputSchema': {'type': 'object', 'properties': {}}}]
    client.post(PREFIX + '/test')
    with Session(engine) as db:
        assert skills.status(db, 'longbridge-technical')['available']
        registry = build_panwatch_tool_registry(db)
        spec = next(tool for tool in registry.registered_tools() if tool.name == 'load_builtin_skill')
        assert set(spec.input_schema['properties']['skill_id']['enum']) == {'longbridge-market-data', 'longbridge-technical'}
        request = RunRequest(run_id='specialist', messages=[ModelMessage(role='user', content='分析 K 线')])
        result = asyncio.run(registry.execute('load_builtin_skill', request, {'skill_id': 'longbridge-technical'}))
        assert result.ok and 'Selected skill: longbridge-technical' in result.summary
        assert 'indicator' in result.summary and result.sources[0].url.endswith('longbridge-technical/SKILL.md')
    client.put(BASE + '/longbridge-technical', json={'enabled': False})
    items = {item['id']: item for item in client.get(BASE).json()['data']['items']}
    assert items['longbridge-market-data']['enabled'] and not items['longbridge-technical']['enabled']


def test_master_switch_updates_only_supported_skills_and_keeps_individual_controls(setup):
    client, engine, provider, _ = setup
    finish(client); client.post(PREFIX + '/test'); client.put(PREFIX, json={'enabled': True})
    before = client.get('/api/mcp-connections').json()['data']
    provider.calls.clear()
    with Session(engine) as db:
        db.add(AppSettings(key='unrelated', value='preserve')); db.commit()
    response = client.put(BASE + '/providers/longbridge', json={'enabled': True})
    assert response.status_code == 200
    items = [i for i in response.json()['data']['items'] if i.get('provider') != 'panwatch']
    assert sum(item['enabled'] for item in items) == 5
    assert all(item['enabled'] == (item['support'] == 'partial') for item in items)
    with Session(engine) as db:
        assert db.query(AppSettings).filter(AppSettings.key.like('builtin_skill.%')).count() == 5
        registry = build_panwatch_tool_registry(db)
        spec = next(tool for tool in registry.registered_tools() if tool.name == 'load_builtin_skill')
        assert len(spec.input_schema['properties']['skill_id']['enum']) == 6
    client.put(BASE + '/longbridge-technical', json={'enabled': False})
    items = [i for i in client.get(BASE).json()['data']['items'] if i.get('provider') != 'panwatch']
    assert sum(item['enabled'] for item in items) == 4
    assert not next(item for item in items if item['id'] == 'longbridge-technical')['enabled']
    for _ in range(2):
        response = client.put(BASE + '/providers/longbridge', json={'enabled': False})
        assert not any(item['enabled'] for item in response.json()['data']['items'] if item.get('provider') != 'panwatch')
        assert next(i for i in response.json()['data']['items'] if i['id'] == 'analyze-a-share-sentiment')['enabled']
    with Session(engine) as db:
        assert db.query(AppSettings).filter(AppSettings.key.like('builtin_skill.%')).count() == 5
        assert db.query(AppSettings).filter_by(key='unrelated').one().value == 'preserve'
        assert skills.status(db, 'analyze-a-share-sentiment')['available']
    request = RunRequest(run_id='bulk-disabled', messages=[ModelMessage(role='user', content='查询行情')])
    assert not asyncio.run(registry.execute('load_builtin_skill', request, {'skill_id': 'longbridge-market-data'})).ok
    assert client.get('/api/mcp-connections').json()['data'] == before
    assert not provider.calls


def test_master_switch_requires_login_and_stores_preferences_without_granting_access(setup):
    client, _, provider, _ = setup
    path = BASE + '/providers/longbridge'
    for body in [{'enabled': 'true'}, {'enabled': True, 'ids': ['longbridge-quant']}]:
        assert client.put(path, json=body).status_code == 422
    assert client.put(BASE + '/providers/custom', json={'enabled': True}).status_code == 404
    items = [i for i in client.put(path, json={'enabled': True}).json()['data']['items'] if i.get('provider') != 'panwatch']
    assert sum(item['enabled'] for item in items) == 5
    assert not any(item['available'] for item in items)
    assert all(item['connection_status'] == 'authorization_required' for item in items)
    assert not provider.calls
    client.headers.pop('Authorization')
    assert client.put(path, json={'enabled': False}).status_code == 401


def test_master_switch_database_failure_does_not_partially_save(setup):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    client, engine, _, _ = setup
    client.put(BASE + '/longbridge', json={'enabled': True})
    with Session(engine) as db:
        db.execute(text("""CREATE TRIGGER reject_skill_save BEFORE INSERT ON app_settings
            WHEN NEW.key = 'builtin_skill.longbridge-portfolio.enabled'
            BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"""))
        db.commit()
        with pytest.raises(IntegrityError):
            skills.configure_supported(db, False)
        db.rollback()
    with Session(engine) as db:
        assert db.query(AppSettings).filter(AppSettings.key.like('builtin_skill.%')).count() == 1
        assert skills.status(db)['enabled']
