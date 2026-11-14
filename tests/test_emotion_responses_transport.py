import asyncio
from types import SimpleNamespace

import pytest

from src.platform.ai.responses_tool_client import ResponsesToolClient, enable_reasoning_tools


class Output:
    def __init__(self, value):
        self.value = value

    def model_dump(self, **kwargs):
        return self.value


class Stream:
    def __init__(self, events):
        self.events = events
        self.closed = False

    async def __aiter__(self):
        for event in self.events:
            yield event

    async def close(self):
        self.closed = True


def transport_fixture(events):
    stream = Stream(events)
    requests = []
    async def create(**kwargs):
        requests.append(kwargs)
        return stream
    return SimpleNamespace(model='gpt-6-astra', total_tokens_used=0, last_usage=None,
                           client=SimpleNamespace(responses=SimpleNamespace(create=create))), stream, requests


def test_responses_preserves_reasoning_call_ids_usage_and_disables_storage():
    native = [
        {'type': 'reasoning', 'id': 'rs1', 'summary': [], 'encrypted_content': 'opaque-test-reasoning'},
        {'type': 'function_call', 'id': 'fc1', 'call_id': 'call1', 'name': 'get_market_facts', 'arguments': '{}', 'status': 'completed'},
    ]
    response = SimpleNamespace(status='completed', output=[Output(i) for i in native], model='gpt-6-astra',
                               usage={'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120})
    transport, stream, requests = transport_fixture([SimpleNamespace(type='response.completed', response=response)])
    wrapper = ResponsesToolClient(transport)
    messages = [{'role': 'system', 'content': 'Facts only'}, {'role': 'user', 'content': 'Analyze'}]
    async def run():
        return [item async for item in wrapper.chat_stream(messages, tools=[{'type': 'function', 'function': {'name': 'get_market_facts', 'parameters': {'type': 'object'}}}], temperature=.2, tool_choice='required')]
    output = asyncio.run(run())[-1][1]
    assert output['tool_calls'][0]['id'] == 'call1'
    assert transport.total_tokens_used == 120
    assert requests[0]['store'] is False and 'temperature' not in requests[0]
    assert requests[0]['reasoning']['effort'] == 'medium'
    assert requests[0]['tools'][0]['strict'] is False
    assert stream.closed
    messages += [{'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call1', 'type': 'function', 'function': {'name': 'get_market_facts', 'arguments': '{}'}}]},
                 {'role': 'tool', 'tool_call_id': 'call1', 'content': '{"facts":true}'}]
    items = wrapper.input_items(messages)
    assert items[2:4] == native
    assert items[-1] == {'type': 'function_call_output', 'call_id': 'call1', 'output': '{"facts":true}'}
    assert 'encrypted_content' not in output  # Opaque reasoning stays inside the transport.


@pytest.mark.parametrize('event', ['response.incomplete', 'response.failed', 'error', None])
def test_incomplete_responses_cannot_be_published(event):
    transport, stream, _ = transport_fixture([SimpleNamespace(type=event)] if event else [])
    async def run():
        return [item async for item in ResponsesToolClient(transport).chat_stream([{'role': 'user', 'content': 'Test'}])]
    with pytest.raises(ValueError, match='responses_incomplete'):
        asyncio.run(run())
    assert stream.closed


def test_only_configured_reasoning_family_is_adapted_and_failover_history_is_valid():
    old = SimpleNamespace(model='compatible-model')
    new = SimpleNamespace(model='gpt-6-astra')
    client = SimpleNamespace(candidates=[(old, 'old'), (new, 'new')])
    enable_reasoning_tools(client)
    assert client.candidates[0][0] is old
    wrapper = client.candidates[1][0]
    assert isinstance(wrapper, ResponsesToolClient)
    enable_reasoning_tools(client)
    assert client.candidates[1][0] is wrapper
    items = wrapper.input_items([{'role': 'assistant', 'tool_calls': [{'id': 'other-model-call', 'function': {'name': 'facts', 'arguments': '{}'}}]}])
    assert items == [{'type': 'function_call', 'call_id': 'other-model-call', 'name': 'facts', 'arguments': '{}'}]
