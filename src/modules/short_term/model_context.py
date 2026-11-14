"""Bound model context while preserving full, immutable UI/audit evidence."""
from copy import deepcopy
from pan_agent import ModelTurn
from src.platform.ai.pan_agent_adapter import FailoverModelAdapter
from .facts import model_facts


class ValidatedDraftAdapter(FailoverModelAdapter):
    """A host-only finalizer after validation; no redundant provider acknowledgement.

    The preceding tool call is the model's actual structured output. The runtime
    still emits its normal completion and cancellation checks. No text or usage
    is fabricated as a provider response.
    """
    def __init__(self, client, accepted):
        super().__init__(client, temperature=0.2)
        self.accepted = accepted

    async def run_turn(self, messages, tools, emit_token, tool_choice=None):
        if self.accepted():
            return ModelTurn(content='', tool_calls=[])
        return await super().run_turn(messages, tools, emit_token, tool_choice)


def agent_facts(facts):
    result = deepcopy(model_facts(facts))
    result.pop('regulatory_events', None)
    result.pop('regulatory_windows', None)
    result.pop('abnormal', None)  # The same calculations are already evidence.
    for item in result['evidence']:
        content = item['content']
        if item['kind'] == 'abnormal_calculation':
            for window in content.get('windows', []):
                window['archived_input_count'] = len(window.pop('inputs', []))
        elif item['kind'] == 'regulatory_window':
            for window in content.get('windows', []):
                window['candidate_count'] = len(window.pop('candidates', []))
                for key in ('upper_case','lower_case'):
                    if window.get(key):window[key].pop('inputs',None)
            for event in content.get('events', []):
                event['excerpt'] = event['excerpt'][:400]
        elif item['kind'] == 'primary_document' and 'excerpt' in content:
            content['excerpt'] = content['excerpt'][:1400]
        else:
            continue
        basis = content.get('price_basis')
        if isinstance(basis, dict) and 'inputs' in basis:
            basis['archived_input_count'] = len(basis.pop('inputs'))
        item['summary'] = item.pop('content')
        item['original_content_hash'] = item.pop('content_hash')
        item['summary_only'] = True
    result['audit_note'] = 'Evidence summaries omit archived daily rows and may shorten document excerpts. Original bodies and hashes remain in the publication; summaries are not hash-identical originals.'
    return result
