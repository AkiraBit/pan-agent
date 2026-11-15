"""Model-owned judgments, separate from host-calculated numbers and freshness."""
from typing import Literal

from pydantic import Field, model_validator

from .schemas import Claim, Contract, Identity, Text

STAGES = ('ice', 'repair', 'expansion', 'heat', 'divergence', 'retreat')
CycleStage = Literal['ice', 'repair', 'expansion', 'heat', 'divergence', 'retreat']
Direction = Literal['improving', 'stable', 'deteriorating', 'mixed', 'insufficient']


class StagePosition(Contract):
    kind: Literal['stage', 'between', 'unknown']
    stages: list[CycleStage] = Field(max_length=2)
    status: Literal['candidate', 'supported', 'conflicted', 'insufficient']
    rationale: Text
    evidence_ids: list[Identity] = Field(max_length=12)

    @model_validator(mode='after')
    def position_shape(self):
        expected = {'stage': 1, 'between': 2, 'unknown': 0}[self.kind]
        if len(self.stages) != expected:
            raise ValueError('stage position needs zero, one or two stages for unknown, stage or between')
        if self.kind == 'between' and (STAGES.index(self.stages[1]) - STAGES.index(self.stages[0])) % len(STAGES) != 1:
            raise ValueError('between requires two adjacent stages in cycle order')
        if self.kind == 'unknown' and self.status != 'insufficient':
            raise ValueError('unknown position must be insufficient')
        if self.kind != 'unknown' and (not self.evidence_ids or self.status == 'insufficient'):
            raise ValueError('positioned stages require evidence and a non-insufficient status')
        return self


class Axis(Contract):
    state: Direction
    explanation: Text
    evidence_ids: list[Identity] = Field(max_length=12)


class EvidenceGroup(Contract):
    group: Literal['G', 'A', 'P', 'R']
    status: Literal['observed', 'proxy', 'missing', 'conflicted']
    explanation: Text
    evidence_ids: list[Identity] = Field(max_length=12)


class ObservationRule(Contract):
    metric: Literal['positive_ratio', 'median', 'p10', 'feedback_mean']
    operator: Literal['gt', 'gte', 'lt', 'lte']
    value: float = Field(allow_inf_nan=False)
    basis: Text
    calibration: Literal['unvalidated'] = 'unvalidated'


class NextCheck(Contract):
    window: Text
    observe: Text
    strengthens: Text
    invalidates: Text
    verification_window: Literal['qualitative', 'next_session_close'] = 'qualitative'
    rule: ObservationRule | None = None
    invalidation_rule: ObservationRule | None = None

    @model_validator(mode='after')
    def numeric_window(self):
        if (self.rule is not None) != (self.verification_window == 'next_session_close'):
            raise ValueError('numeric conditions require verification_window=next_session_close; prose uses qualitative')
        return self


class OverviewAnalysis(Contract):
    title: Text
    summary: Text
    direction: Direction
    direction_reason: Text
    stage: StagePosition
    loss_relief: Axis
    profit_diffusion: Axis
    groups: list[EvidenceGroup] = Field(min_length=4, max_length=4)
    supports: list[Claim] = Field(min_length=1, max_length=6)
    counters: list[Claim] = Field(min_length=1, max_length=6)
    next_checks: list[NextCheck] = Field(min_length=1, max_length=4)
    limitations: list[Text] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def four_groups(self):
        if {g.group for g in self.groups} != {'G', 'A', 'P', 'R'}:
            raise ValueError('exactly one assessment for each of G/A/P/R is required')
        return self


class OverviewRefresh(Contract):
    request_key: str = Field(min_length=8, max_length=100)
    language: Literal['zh-CN', 'en-US'] = 'zh-CN'
    force: bool = False
