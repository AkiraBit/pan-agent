"""Versioned sentiment publications. Facts are supplied by the host, not the model."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2400)]
Identity = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:-]{1,100}$")]
Symbol = Annotated[str, Field(pattern=r"^(?:[036]\d{5})\.(?:SH|SZ)$")]
Stage = Literal["unknown", "startup", "expansion", "divergence", "repair", "retreat"]
Page = Literal["overview", "cycle", "playbook", "stock", "evidence", "review", "agent"]
Kind = Literal["verdict", "market", "cycles", "watchlist", "scenarios", "conditions", "evidence", "memory", "changes", "runs", "data_quality"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Claim(Contract):
    text: Text
    evidence_ids: list[Identity] = Field(min_length=1, max_length=12)


class Relation(Contract):
    source: Symbol
    target: Symbol
    kind: Literal["business_relation", "name_association", "observed_co_move", "relay_hypothesis", "contradiction"]
    explanation: Text
    evidence_ids: list[Identity] = Field(min_length=1, max_length=8)


class Cycle(Contract):
    id: Identity
    name: Text
    stage: Stage
    summary: Text
    symbols: list[Symbol] = Field(min_length=1, max_length=20)
    evidence_ids: list[Identity] = Field(min_length=1, max_length=12)
    relations: list[Relation] = Field(default_factory=list, max_length=20)


class WatchStock(Contract):
    symbol: Symbol
    role: Text
    cycle_id: Identity | None = None
    thesis: Text
    invalidation: Text
    evidence_ids: list[Identity] = Field(min_length=1, max_length=12)


class PriceExpression(Contract):
    symbol: Symbol
    metric: Literal["price", "change_pct"]
    operator: Literal["gte", "lte"]
    value: float


class MetricCheck(Contract):
    symbol: Symbol
    metric: Literal['price', 'change_pct', 'open_change_pct', 'amount_cny',
                    'auction_change_pct', 'matched_amount_cny', 'unmatched_ratio']
    operator: Literal['gte', 'lte']
    value: float


class VerificationRule(Contract):
    checks: list[MetricCheck] = Field(min_length=1, max_length=8)
    mode: Literal['all', 'any'] = 'all'
    persistence_seconds: int = Field(default=0, ge=0, le=1800)
    invalidation_checks: list[MetricCheck] = Field(default_factory=list, max_length=8)


class Condition(Contract):
    id: Identity
    title: Text
    subject: Symbol | None = None
    window: Literal["premarket", "auction", "opening", "afternoon", "close", "next_session"]
    criterion: Text
    invalidation: Text
    evidence_ids: list[Identity] = Field(min_length=1, max_length=12)
    expression: PriceExpression | None = None
    rule: VerificationRule | None = None


class Scenario(Contract):
    id: Identity
    title: Text
    thesis: Text
    condition_ids: list[Identity] = Field(min_length=1, max_length=12)
    supports: list[Claim] = Field(min_length=1, max_length=6)
    counters: list[Claim] = Field(min_length=1, max_length=6)
    invalidation: Text


class Block(Contract):
    id: Identity
    page: Page
    kind: Kind
    title: Text
    entity_ids: list[Identity] = Field(default_factory=list, max_length=30)


class AnalysisDraft(Contract):
    title: Text
    summary: Text
    stage: Stage
    supports: list[Claim] = Field(min_length=1, max_length=8)
    counters: list[Claim] = Field(min_length=1, max_length=8)
    cycles: list[Cycle] = Field(default_factory=list, max_length=5)
    watchlist: list[WatchStock] = Field(min_length=1, max_length=20)
    scenarios: list[Scenario] = Field(min_length=2, max_length=4)
    conditions: list[Condition] = Field(min_length=3, max_length=16)
    memory_summary: Text
    open_questions: list[Text] = Field(min_length=1, max_length=12)
    changes: list[Text] = Field(min_length=1, max_length=8)
    blocks: list[Block] = Field(min_length=7, max_length=24)

    @model_validator(mode="after")
    def unique_and_linked(self):
        for collection, key in [(self.cycles, "id"), (self.watchlist, "symbol"),
                                (self.scenarios, "id"), (self.conditions, "id"), (self.blocks, "id")]:
            values = [getattr(item, key) for item in collection]
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {key}")
        cycles = {c.id for c in self.cycles}
        symbols = {s.symbol for s in self.watchlist}
        conditions = {c.id for c in self.conditions}
        for stock in self.watchlist:
            if stock.cycle_id and stock.cycle_id not in cycles:
                raise ValueError("unknown cycle_id")
        for scenario in self.scenarios:
            if not set(scenario.condition_ids) <= conditions:
                raise ValueError("unknown condition_id")
        for condition in self.conditions:
            if condition.subject and condition.subject not in symbols:
                raise ValueError("condition subject must be in watchlist")
            if condition.expression and condition.expression.symbol not in symbols:
                raise ValueError("expression symbol must be in watchlist")
            if condition.rule and not {x.symbol for x in [*condition.rule.checks, *condition.rule.invalidation_checks]} <= symbols:
                raise ValueError('rule symbols must be in watchlist')
        return self


class RunCreate(Contract):
    request_key: Annotated[str, Field(min_length=8, max_length=100)]
    target_trade_date: date | None = None
    language: Literal["zh-CN", "en-US"] = "zh-CN"


class WorkspaceSettings(Contract):
    focus_symbols: list[Symbol] = Field(default_factory=list, max_length=20)
    schedule_enabled: bool = False
    schedule_time: Annotated[str, Field(pattern=r"^0[6-9]:[0-5]\d$")] = "08:45"
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    monitoring_enabled: bool = False
    monitor_interval_seconds: int = Field(default=30, ge=15, le=120)
    postmarket_enabled: bool = False
    postmarket_time: Annotated[str, Field(pattern=r'^1[5-8]:[0-5]\d$')] = '15:10'

    @field_validator("focus_symbols")
    @classmethod
    def unique_symbols(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate symbols")
        for symbol in value:
            if (symbol.startswith("6")) != symbol.endswith("SH"):
                raise ValueError("symbol/exchange mismatch")
        return value

    @field_validator("schedule_time")
    @classmethod
    def before_open(cls, value):
        if value > "09:10":
            raise ValueError("schedule must be before 09:10 Asia/Shanghai")
        return value


class ContextCreate(Contract):
    content: Annotated[str, Field(min_length=1, max_length=4000)]
    source_url: Annotated[str, Field(max_length=2048)] | None = None

    @field_validator("source_url")
    @classmethod
    def safe_source(cls, value):
        from urllib.parse import urlparse
        if value and (urlparse(value).scheme not in {"https", "http"} or not urlparse(value).netloc):
            raise ValueError("source must be an http(s) URL")
        return value or None


class ContextUpdate(Contract):
    status: Literal["open", "archived"]


class MonitorCommand(Contract):
    enabled: bool


class ReviewCreate(Contract):
    request_key: Annotated[str, Field(min_length=8, max_length=100)]
    publication_id: Identity


class ReviewFinding(Contract):
    condition_id: Identity
    assessment: Literal['supported', 'contradicted', 'inconclusive']
    explanation: Text
    evidence_ids: list[Identity] = Field(min_length=1, max_length=12)


class ReviewDraft(Contract):
    title: Text
    summary: Text
    findings: list[ReviewFinding] = Field(min_length=1, max_length=16)
    lessons: list[Text] = Field(min_length=1, max_length=8)
    next_day_focus: list[Text] = Field(min_length=1, max_length=10)
    memory_summary: Text
    open_questions: list[Text] = Field(min_length=1, max_length=12)


class AuctionSettings(Contract):
    enabled: bool = False
    endpoint: str = Field(default='', max_length=2048)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    provider_name: str = Field(default='licensed_gateway', min_length=1, max_length=80)

    @field_validator('endpoint')
    @classmethod
    def endpoint_url(cls, value):
        from urllib.parse import urlparse
        if not value:
            return value
        p = urlparse(value)
        if p.username or p.password or p.query or p.fragment or not p.hostname:
            raise ValueError('invalid auction endpoint')
        if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('127.0.0.1', 'localhost', '::1')):
            raise ValueError('HTTPS or loopback gateway required')
        return value.rstrip('/')

    @model_validator(mode='after')
    def configured(self):
        if self.enabled and not self.endpoint:
            raise ValueError('enabled auction source requires endpoint')
        return self
