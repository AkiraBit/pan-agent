"""Market research reads from the workspace's configured data provider."""

import json
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.modules.market.research_workspaces import PROVIDERS, WORKSPACES, view_definition
from src.platform.marketdata import fuyao_credentials, fuyao_rest
from src.platform.marketdata.source_activation import active_source, paused_providers, provider_group
from src.platform.persistence.database import get_db
from src.platform.persistence.models import DataSource
from src.platform.scheduling.trading_calendar import is_trading_day
from src.web.errors import api_error

router = APIRouter()
SHANGHAI = ZoneInfo("Asia/Shanghai")


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indicator_code: str = Field(pattern=r"^[a-zA-Z0-9_]+$", max_length=128)
    operator: str = Field(min_length=1, max_length=32)
    value: FiniteFloat | Annotated[str, Field(min_length=1, max_length=128)]


class Conditions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buy: list[Rule] = Field(min_length=1, max_length=8)
    sell: list[Rule] = Field(min_length=1, max_length=8)


class ResearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=16)
    conditions: Conditions | None = None


def source_rows(db, capability, operations, *, active_only=False):
    query = select(DataSource).where(DataSource.provider.in_(list(PROVIDERS))).where(
        ((DataSource.provider == "fuyao") & DataSource.type.in_([fuyao_rest.TYPE_PREFIX + op for op in operations]))
        | ((DataSource.provider != "fuyao") & (DataSource.type == capability)))
    if active_only:
        query = query.where(active_source())
    return db.scalars(query.order_by(DataSource.id)).all()


def workspace_views(capability):
    if capability not in WORKSPACES:
        raise api_error(404, "research_workspace_not_found", "此研究业务不存在。")
    return WORKSPACES[capability]


@router.get("/{capability}")
def workspace(capability: str, db: Session = Depends(get_db)):
    views = workspace_views(capability)
    configured = fuyao_credentials.configured(fuyao_credentials.read(db))
    paused = paused_providers(db)
    sources = {}
    for row in source_rows(db, capability, (view.operation for view in views)):
        status = sources.setdefault(row.provider, {"name": "同花顺" if row.provider == "fuyao" else row.name,
            "provider": row.provider, "enabled": False, "priority": row.priority,
            "available": row.provider != "fuyao" or configured})
        status["enabled"] |= bool(row.enabled and provider_group(row.provider) not in paused)
    today = datetime.now(SHANGHAI).date()
    last_trade = next((d for n in range(15) if is_trading_day("CN", d := today - timedelta(days=n))), None)
    return {"views": [view_definition(view) for view in views], "sources": list(sources.values()),
            "today": today.isoformat(), "last_trade_date": last_trade.isoformat() if last_trade else None}


def query_filters(view, body: ResearchQuery):
    filters = body.filters.copy()
    expected = view.id == "strategy"
    if expected and (not body.conditions or filters.keys() & {"buy_conditions", "sell_conditions"}):
        raise api_error(422, "research_strategy_required", "请填写买入和卖出条件。")
    if not expected and body.conditions:
        raise api_error(422, "research_query_invalid", "此业务查询不接受回测条件。")
    if body.conditions:
        for action in ("buy", "sell"):
            rules = [rule.model_dump() for rule in getattr(body.conditions, action)]
            filters[action + "_conditions"] = json.dumps(rules[0] if len(rules) == 1 else rules,
                                                          ensure_ascii=False, allow_nan=False)
        # The public contract accepts numbers; the product requires a positive
        # amount and an integer purchase count for the portfolio simulation.
        try:
            times, amount = float(filters["max_buy_times"]), float(filters["per_buy_amount"])
            if not 1 <= times <= 10000 or not times.is_integer() or not 0 < amount < float("inf"):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise api_error(422, "research_query_invalid", "买入次数须为 1–10000 的整数，单次金额须为正数。") from None
    try:
        return fuyao_rest.query_params(fuyao_rest.OPERATIONS[view.operation], filters)
    except fuyao_rest.InvalidQuery as exc:
        raise api_error(422, "research_query_invalid", str(exc)) from None


def browser_data(value):
    """Keep provider IDs and large integers exact in JavaScript."""
    if type(value) is int and abs(value) > (1 << 53) - 1:
        return str(value)
    if isinstance(value, dict):
        return {key: browser_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [browser_data(item) for item in value]
    return value


@router.post("/{capability}/{view_id}")
async def load_view(capability: str, view_id: str, body: ResearchQuery, db: Session = Depends(get_db)):
    view = next((item for item in workspace_views(capability) if item.id == view_id), None)
    if view is None:
        raise api_error(404, "research_workspace_not_found", "此研究视图不存在。")
    filters = query_filters(view, body)
    candidates = source_rows(db, capability, (view.operation,), active_only=True)
    if not candidates:
        raise api_error(409, "research_source_disabled", "请先在「数据源」启用此视图使用的接口。")
    has_key = fuyao_credentials.configured(fuyao_credentials.read(db))
    candidates = [(row.provider, row.name) for row in candidates if row.provider != "fuyao" or has_key]
    if not candidates:
        raise api_error(409, "provider_key_required", "请先在设置中配置同花顺 API Key。")
    bind = db.get_bind()
    db.rollback()
    provider, name = next(((p, n) for p, n in candidates if p == "fuyao"), candidates[0])
    try:
        data = await PROVIDERS[provider](view.operation, filters, bind=bind)
    except RuntimeError as exc:
        raise api_error(502, "research_source_unavailable", str(exc)) from None
    return {"provider": provider, "source_name": name, "result": browser_data(data)}
