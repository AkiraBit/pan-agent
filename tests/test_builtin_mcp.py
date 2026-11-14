"""HTTP API + OAuth/MCP protocol replay; no real account or model credentials."""
import asyncio
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.modules.administration import longbridge_mcp as service, mcp_transport
from src.modules.administration.api import auth, mcp_connections
from src.platform.persistence.database import Base, get_db
from src.platform.persistence.models import AppSettings, MCPConnection
from src.web.response import ResponseWrapperMiddleware

PREFIX = '/api/mcp-connections/longbridge'
BROWSER = 'browser-binding-' + 'x' * 40


class Provider:
    def __init__(self):
        self.calls = []
        self.refresh_error = False
        self.on_token = None
        self.tools = [{'name': name, 'description': name, 'inputSchema': {'type': 'object', 'properties': {}}}
                      for name in [*service.READ_TOOLS, 'submit_order', 'unknown_future_tool']]

    def handle(self, request):
        self.calls.append(request)
        path = request.url.path
        if path.endswith('/.well-known/oauth-authorization-server'):
            return httpx.Response(200, json={
                'authorization_endpoint': service.ENDPOINTS['cn'] + '/oauth2/authorize',
                'token_endpoint': service.ENDPOINTS['cn'] + '/oauth2/token',
                'registration_endpoint': 'https://openapi.longbridge.cn/oauth2/register',
                'code_challenge_methods_supported': ['S256']})
        if path.endswith('/register'):
            assert json.loads(request.content)['scope'] == 'account.read'
            return httpx.Response(201, json={'client_id': 'test-client'})
        if path.endswith('/token'):
            data = parse_qs(request.content.decode())
            if self.on_token:
                self.on_token()
            if data['grant_type'] == ['refresh_token'] and self.refresh_error:
                return httpx.Response(400, json={'error': 'invalid_grant'})
            return httpx.Response(200, json={'access_token': 'PRIVATE-ACCESS', 'refresh_token': 'PRIVATE-REFRESH',
                                            'token_type': 'Bearer', 'expires_in': 3600})
        if request.method == 'DELETE':
            return httpx.Response(204)
        payload = json.loads(request.content)
        assert request.headers['authorization'] == 'Bearer PRIVATE-ACCESS'
        if payload['method'] == 'notifications/initialized':
            return httpx.Response(202)
        result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fixture', 'version': '1'}}
        if payload['method'] == 'tools/list':
            result = {'tools': self.tools}
            # Exercise SSE framing, keepalives and a nonmatching notification.
            stream = ': keepalive\n\ndata: {"jsonrpc":"2.0","method":"notifications/message"}\n\n'
            stream += 'data: ' + json.dumps({'jsonrpc': '2.0', 'id': payload['id'], 'result': result}) + '\n\n'
            return httpx.Response(200, text=stream, headers={'Content-Type': 'text/event-stream'})
        if payload['method'] == 'tools/call':
            assert payload['params']['name'] in service.READ_TOOLS
            result = {'content': [{'type': 'text', 'text': 'Synthetic quote: 100'}], 'isError': False}
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': payload['id'], 'result': result},
                              headers={'mcp-session-id': 'fixture-session'})


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(service, 'get_data_dir', lambda: tmp_path)
    monkeypatch.setattr(auth, 'get_jwt_secret', lambda: 'test-signing-key-' * 4)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AppSettings(key=auth.PASSWORD_HASH_KEY, value='configured'))
        db.commit()
    app = FastAPI()
    app.include_router(mcp_connections.router, prefix='/api/mcp-connections')
    app.add_middleware(ResponseWrapperMiddleware)
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    provider = Provider()
    factory = lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(provider.handle), **kwargs)
    monkeypatch.setattr(service, 'http_client', factory)
    monkeypatch.setattr(mcp_transport, 'http_client', factory)
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + auth.create_token()[0]
        client.headers['Origin'] = 'http://localhost:5183'
        yield client, engine, provider, tmp_path
    engine.dispose()


def begin(client):
    response = client.post(PREFIX + '/authorize', json={'region': 'cn', 'browser_key': BROWSER})
    assert response.status_code == 200, response.text
    return response.json()['data']


def finish(client, start=None):
    start = start or begin(client)
    response = client.post(PREFIX + '/callback', json={
        'state': start['state'], 'browser_key': BROWSER, 'code': 'one-time-code'})
    assert response.status_code == 200, response.text
    return response.json()['data']


def test_oauth_mcp_and_credential_persistence(setup):
    client, engine, provider, path = setup
    initial = client.get('/api/mcp-connections').json()['data']['items'][0]
    assert not initial['authorized'] and not initial['enabled']
    start = begin(client)
    query = parse_qs(urlsplit(start['authorization_url']).query)
    assert query['scope'] == ['account.read'] and query['code_challenge_method'] == ['S256']
    assert query['redirect_uri'] == ['http://localhost:5183/integrations/mcp/callback']
    with Session(engine) as db:
        pending = service.unseal(service.read(db).pending)
        expected = base64.urlsafe_b64encode(hashlib.sha256(pending['verifier'].encode()).digest()).rstrip(b'=').decode()
        assert expected == query['code_challenge'][0]
    authorized = finish(client, start)
    assert authorized['authorized'] and not authorized['enabled']
    assert authorized['connected_at'] <= time.time() and authorized['connected_at'] > time.time() - 5
    tested = client.post(PREFIX + '/test').json()['data']
    assert {tool['name'] for tool in tested['tools']} == set(service.READ_TOOLS)
    assert tested['server_version'] == '1'
    assert all(tool['description'] == tool['name'] for tool in tested['tools'])
    assert tested['connected_at'] == authorized['connected_at']
    assert client.put(PREFIX, json={'enabled': True}).json()['data']['enabled']
    with Session(engine) as db:
        row = service.read(db)
        assert 'PRIVATE' not in row.credentials and not row.pending
        assert service.unseal(row.credentials)['access_token'] == 'PRIVATE-ACCESS'
        assert asyncio.run(service.remote(db, 'quote', {}))['content'][0]['text'] == 'Synthetic quote: 100'
    assert path.joinpath('mcp-credentials.key').stat().st_mode & 0o777 == 0o600
    public = client.get('/api/mcp-connections').text
    assert 'PRIVATE' not in public and 'test-client' not in public and 'verifier' not in public
    token_request = next(r for r in provider.calls if r.url.path.endswith('/token'))
    assert parse_qs(token_request.content.decode())['code_verifier'] == [pending['verifier']]
    # New DB session is the same path used after a restart.
    with Session(engine) as db:
        assert service.status(db)['enabled']


def test_login_required_even_before_initial_setup(setup):
    client, engine, _, _ = setup
    client.headers.pop('Authorization')
    assert client.get('/api/mcp-connections').status_code == 401
    with Session(engine) as db:
        db.query(AppSettings).delete(); db.commit()
    assert client.get('/api/mcp-connections').status_code == 401


def test_no_arbitrary_provider_install_or_configuration(setup):
    client, _, provider, _ = setup
    assert client.post('/api/mcp-connections/custom', json={'url': 'http://127.0.0.1'}).status_code == 404
    assert client.post(PREFIX + '/authorize', json={'region': 'custom', 'browser_key': BROWSER}).status_code == 422
    assert client.post(PREFIX + '/authorize', json={'browser_key': BROWSER, 'command': 'npx', 'url': 'https://other.example'}).status_code == 422
    assert client.put(PREFIX, json={'enabled': True}).status_code == 409
    assert not provider.calls


def test_browser_binding_expiry_replay_and_cancel(setup):
    client, engine, provider, _ = setup
    start = begin(client)
    body = {'state': start['state'], 'browser_key': 'another-browser-' * 4, 'code': 'code'}
    assert client.post(PREFIX + '/callback', json=body).status_code == 409
    body['browser_key'] = BROWSER
    with Session(engine) as db:
        row = service.read(db); row.pending_until = 1; db.commit()
    assert client.post(PREFIX + '/callback', json=body).status_code == 409
    start = begin(client)
    body.update(state=start['state'], error='access_denied', code=None)
    assert client.post(PREFIX + '/callback', json=body).status_code == 200
    assert client.post(PREFIX + '/callback', json=body).status_code == 409
    assert not any(r.url.path.endswith('/token') for r in provider.calls)
    begin(client)
    assert not client.delete(PREFIX + '/authorization').json()['data']['pending']


def test_callback_does_not_restore_disconnected_connection(setup):
    client, engine, provider, _ = setup
    start = begin(client)
    def disconnect_during_exchange():
        with Session(engine) as db:
            service.disconnect(db)
    provider.on_token = disconnect_during_exchange
    response = client.post(PREFIX + '/callback', json={'state': start['state'], 'browser_key': BROWSER, 'code': 'code'})
    assert response.status_code == 409
    assert not client.get('/api/mcp-connections').json()['data']['items'][0]['authorized']


def test_token_refresh_and_revocation_failure(setup):
    client, engine, provider, _ = setup
    finish(client)
    with Session(engine) as db:
        row = service.read(db)
        credentials = service.unseal(row.credentials)
        credentials['expires_at'] = 1
        row.credentials = service.seal(credentials); db.commit()
        asyncio.run(service.access_token(db))
        assert service.unseal(service.read(db).credentials)['expires_at'] > time.time()
        row = service.read(db); row.credentials = service.seal(credentials); db.commit()
        provider.refresh_error = True
        with pytest.raises(HTTPException):
            asyncio.run(service.access_token(db))
        assert not service.status(db)['authorized']
        assert service.status(db)['error_code'] == 'mcp_authorization_required'


def test_missing_key_fails_closed_without_replacing_key(setup):
    client, engine, _, path = setup
    finish(client)
    path.joinpath('mcp-credentials.key').unlink()
    assert client.post(PREFIX + '/test').status_code == 409
    assert not path.joinpath('mcp-credentials.key').exists()
    assert client.delete(PREFIX).status_code == 200


def test_unsafe_redirect_rejected_before_registration(setup):
    client, _, provider, _ = setup
    for origin in ['http://example.com', 'https://user:password@example.com', 'https://example.com/path']:
        client.headers['Origin'] = origin
        assert client.post(PREFIX + '/authorize', json={'browser_key': BROWSER}).status_code == 409
    assert not provider.calls


def test_disable_disconnect_and_write_tools_cannot_be_called(setup):
    client, engine, provider, _ = setup
    finish(client); client.post(PREFIX + '/test'); client.put(PREFIX, json={'enabled': True})
    from src.modules.assistant.tools import build_panwatch_tool_registry
    from pan_agent import RunRequest, ModelMessage
    with Session(engine) as db:
        registry = build_panwatch_tool_registry(db)
        assert 'longbridge_quote' in {s.name for s in registry.registered_tools()}
        assert 'longbridge_submit_order' not in {s.name for s in registry.registered_tools()}
        request = RunRequest(run_id='builtin-test', messages=[ModelMessage(role='user', content='长桥报价')])
        result = asyncio.run(registry.execute('longbridge_quote', request, {}))
        assert result.ok and 'Synthetic quote' in result.summary
        assert 'PRIVATE' not in result.model_dump_json()
        with pytest.raises(HTTPException):
            asyncio.run(service.remote(db, 'submit_order', {}))
        service.save(db, service.read(db).version, enabled=False)
        count = len(provider.calls)
        assert not asyncio.run(registry.execute('longbridge_quote', request, {})).ok
        assert len(provider.calls) == count
    disconnected = client.delete(PREFIX).json()['data']
    assert not disconnected['authorized'] and not disconnected['enabled'] and not disconnected['tools']
    assert disconnected['connected_at'] is None and not disconnected['account_label'] and not disconnected['server_version']


def test_migration_is_additive_and_idempotent():
    from src.platform.persistence.migrations import _m143_builtin_mcp_connections, _m144_mcp_connection_details
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        _m143_builtin_mcp_connections(conn)
        conn.execute(text("INSERT INTO mcp_connections(provider) VALUES('longbridge')"))
        _m143_builtin_mcp_connections(conn)
        assert conn.execute(text('SELECT enabled, version FROM mcp_connections')).one() == (0, 0)
        _m144_mcp_connection_details(conn)
        _m144_mcp_connection_details(conn)
        assert conn.execute(text('SELECT connected_at, account_label, server_version FROM mcp_connections')).one() == (None, '', '')
    engine.dispose()


def test_production_assistant_runtime_calls_enabled_mcp_and_persists_evidence(setup):
    """Real runtime and HTTP transport, scripted model and synthetic broker responses."""
    from pan_agent import ModelMessage, RunRequest, RunStatus
    from src.modules.assistant.repository import AssistantRepository
    from src.modules.assistant.service import AssistantService
    from src.modules.assistant.task_runner import DurableRuntimeEventSink

    client, engine, _, _ = setup
    finish(client); client.post(PREFIX + '/test'); client.put(PREFIX, json={'enabled': True})
    class ScriptedModel:
        model = 'scripted-mcp-contract'
        step = 0
        async def chat_stream(self, messages, **kwargs):
            exposed = {item['function']['name'] for item in kwargs.get('tools', [])}
            assert 'longbridge_quote' in exposed
            assert 'longbridge_submit_order' not in exposed
            self.step += 1
            yield 'message', {'content': 'Synthetic quote: 100' if self.step > 1 else '', 'model': self.model,
                'tool_calls': [{'id': 'quote-call', 'name': 'longbridge_quote', 'arguments': '{}'}] if self.step == 1 else [],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 10}}

    with Session(engine) as db:
        repository = AssistantRepository(db)
        conversation = repository.create_conversation(stock_symbol=None, stock_market=None, initial_context=None)
        task = repository.create_task(conversation_id=conversation.id, user_message_id=None, context={})
        repository.claim_task(task.id)
        assistant = AssistantService(repository)
        request = RunRequest(run_id=str(task.id), messages=[ModelMessage(role='user', content='请用长桥查询报价')])
        sink = DurableRuntimeEventSink(assistant, task.id)
        async def run():
            result = await assistant.build_runtime(ScriptedModel()).run(request, sink)
            await sink.flush()
            return result
        result = asyncio.run(run())
        assert result.status is RunStatus.COMPLETED, result.error_code
        invocations = repository.list_task_tool_invocations(task.id)
        quote = next(item for item in invocations if item.tool_name == 'longbridge_quote')
        assert quote.result_data['provider'] == 'longbridge'
        assert 'PRIVATE' not in str(quote.result_data)


def test_discovery_drops_malformed_and_duplicate_tools(setup):
    client, _, provider, _ = setup
    finish(client)
    provider.tools.extend([None, {'name': ['quote']}, {'name': 'quote', 'inputSchema': None}, provider.tools[0]])
    response = client.post(PREFIX + '/test')
    assert response.status_code == 200
    assert len(response.json()['data']['tools']) == len(service.READ_TOOLS)


def test_token_refresh_cannot_restore_a_disconnected_connection(setup):
    client, engine, provider, _ = setup
    finish(client)
    with Session(engine) as db:
        row = service.read(db)
        credential = service.unseal(row.credentials); credential['expires_at'] = 1
        row.credentials = service.seal(credential); db.commit()
    def revoke_during_refresh():
        with Session(engine) as db:
            service.disconnect(db)
    provider.on_token = revoke_during_refresh
    assert client.post(PREFIX + '/test').status_code == 409
    assert not client.get('/api/mcp-connections').json()['data']['items'][0]['authorized']


@pytest.mark.parametrize('response', [
    httpx.Response(200, json=[]),
    httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1, 'error': {'message': 'PRIVATE internal error'}}),
    httpx.Response(200, text='x' * 1_048_577),
    httpx.Response(401, json={'error': 'PRIVATE auth error'}),
])
def test_transport_errors_are_bounded_and_do_not_expose_upstream_details(monkeypatch, response):
    factory = lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response), **kwargs)
    monkeypatch.setattr(mcp_transport, 'http_client', factory)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(mcp_transport.query(service.ENDPOINTS['cn'], 'synthetic-token', None, None))
    assert 'PRIVATE' not in str(caught.value.detail)
