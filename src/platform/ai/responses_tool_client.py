"""Responses transport for reasoning tool calls, scoped to an individual agent run.

https://developers.openai.com/api/docs/guides/function-calling
Keep encrypted reasoning items with their function calls while using store=False.
Other configured model families retain the existing Chat Completions transport.
"""
from __future__ import annotations

import json

from pan_agent_token_meter import normalize_provider_usage


class ResponsesToolClient:
    def __init__(self, transport):
        self.transport = transport
        self.outputs = {}

    def __getattr__(self, key):
        return getattr(self.transport, key)

    def input_items(self, messages):
        items = []
        for message in messages:
            role = message['role']
            if role == 'tool':
                items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'],
                              'output': message.get('content') or ''})
            elif role == 'assistant' and message.get('tool_calls'):
                calls = message['tool_calls']
                identity = tuple(call['id'] for call in calls)
                if native := self.outputs.get(identity):
                    items.extend(native)
                    continue
                # A failover candidate has no native reasoning from the previous model.
                if message.get('content'):
                    items.append({'role': 'assistant', 'content': message['content']})
                for call in calls:
                    items.append({'type': 'function_call', 'call_id': call['id'],
                                  'name': call['function']['name'], 'arguments': call['function']['arguments']})
            else:
                items.append({'role': role, 'content': message.get('content') or ''})
        return items

    async def chat_stream(self, messages, tools=None, temperature=None, tool_choice=None):
        # Sampling temperature is incompatible with reasoning on this model family.
        kwargs = {'model': self.model, 'input': self.input_items(messages), 'stream': True,
                  'store': False, 'include': ['reasoning.encrypted_content'],
                  'reasoning': {'effort': 'medium'}, 'max_output_tokens': 24000}
        if tools:
            kwargs['tools'] = [{'type': 'function', **tool['function'], 'strict': False} for tool in tools]
        if tool_choice:
            kwargs['tool_choice'] = tool_choice
        stream = await self.client.responses.create(**kwargs)
        response = None
        try:
            async for event in stream:
                if event.type == 'response.output_text.delta':
                    yield 'token', event.delta
                elif event.type == 'response.completed':
                    response = event.response
                elif event.type in {'response.failed', 'response.incomplete', 'error'}:
                    raise ValueError('responses_incomplete')
        finally:
            await stream.close()
        if response is None or response.status != 'completed':
            raise ValueError('responses_incomplete')
        output = [item.model_dump(mode='json', exclude_none=True) for item in response.output]
        calls = [{'id': item['call_id'], 'name': item['name'], 'arguments': item['arguments']}
                 for item in output if item['type'] == 'function_call']
        if calls:
            self.outputs[tuple(call['id'] for call in calls)] = output
        usage = normalize_provider_usage(response.usage, model=response.model)
        self.transport.last_usage = usage
        if usage:
            self.transport.total_tokens_used += usage.total_tokens or 0
        content = ''.join(part.get('text', '') for item in output if item['type'] == 'message'
                          for part in item.get('content', []) if part.get('type') == 'output_text')
        yield 'message', {'content': content, 'tool_calls': calls, 'model': response.model,
                          'usage': usage.model_dump(mode='json') if usage else None}


def enable_reasoning_tools(client):
    """Use Responses for configured GPT-6 candidates without changing global settings."""
    for index, (transport, label) in enumerate(getattr(client, 'candidates', [])):
        if transport.model.startswith(('gpt-6-', 'gpt-6.')) and not isinstance(transport, ResponsesToolClient):
            client.candidates[index] = (ResponsesToolClient(transport), label)
    return client
