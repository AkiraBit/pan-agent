"""数据源管理 API"""

import logging
from typing import Literal
from fastapi import APIRouter, Depends, Query
from datetime import datetime
from sqlalchemy.orm import Session
from pydantic import BaseModel, StrictBool

from src.modules.market import source_test_settings
from src.platform.marketdata import (call_order, ftshare_rest, fuyao_business, fuyao_credentials, fuyao_rest,
                                     provider_credentials, source_activation)
from src.platform.persistence.database import get_db
from src.platform.persistence.models import DataSource
from src.web.errors import api_error

logger = logging.getLogger(__name__)

router = APIRouter()


# 数据源类型说明
TYPE_LABELS = {
    "etf_turnover": "ETF 成交额",
    "etf_nav": "ETF 净值", "etf_history": "ETF 历史行情",
    "news": "新闻资讯",
    "kline": "K线数据",
    "capital_flow": "资金流向",
    "quote": "实时行情",
    "events": "事件日历",
    "chart": "K线截图",
    "flash_news": "快讯",
    "fundamentals": "基本面",
    "dragon_tiger": "龙虎榜",
    "margin": "融资融券",
    "shareholders": "股东户数",
    "dividend": "分红",
    "northbound": "北向资金",
    "stock_search": "标的检索", "trading_calendar": "交易日历", "index_quote": "指数行情",
    "index_kline": "指数日 K 线", "index_constituents": "指数与板块",
    "market_sentiment": "热榜与股票池", "auction": "集合竞价", "ipo": "新股发行与申购",
    "fund_holdings": "基金持仓与配置", "fund_research": "基金与基金经理研究",
    "fund_backtest": "基金回测", "futures_research": "期货研究", "options_research": "期权研究",
    "etf_adjusted_history": "ETF 前复权日线",
}


class DataSourceCreate(BaseModel):
    name: str
    type: str  # news / kline / capital_flow / quote / events / chart / flash_news
    provider: str
    config: dict = {}
    enabled: bool = True
    priority: int = 0
    supports_batch: bool = False
    test_symbols: list[str] = []


class DataSourceUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    provider: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    priority: int | None = None
    supports_batch: bool | None = None
    test_symbols: list[str] | None = None
    test_params: dict | None = None


class DataSourceMove(BaseModel):
    direction: Literal[-1, 1, "first"]


class DataSourceProviderUpdate(BaseModel):
    enabled: StrictBool


class DataSourceResponse(BaseModel):
    id: int
    name: str
    type: str
    type_label: str = ""
    provider: str
    config: dict
    enabled: bool
    priority: int
    supports_batch: bool = False
    test_symbols: list[str] = []

    class Config:
        from_attributes = True


# 已接入 marketdata 新引擎的数据类型(随各类型逐步迁移扩充)
_ENGINE_ATTACHED_TYPES = {
    "news",
    "quote",
    "kline",
    "capital_flow",
    "events",
    "flash_news",
    "fundamentals",
    "dragon_tiger",
    "margin",
    "shareholders",
    "dividend",
    "northbound",
}


def _is_orphan(type_: str, provider: str) -> bool:
    """判定 (type, provider) 是否为孤儿数据源:不在包内引擎 vendor 集合、也不在当前 seed 列表里。

    与 server.reconcile_data_sources 的孤儿判定保持一致(legal = 包内集合 | seed 集合)。
    """
    from marketdata import PACKAGE_VENDORS_BY_TYPE
    from server import _seed_providers_by_type

    legal = PACKAGE_VENDORS_BY_TYPE.get(type_, frozenset()) | _seed_providers_by_type().get(type_, set())
    return provider not in legal


def _to_response(source: DataSource, health_map: dict | None = None,
                 fuyao_configured: bool | None = None, ftshare_configured: bool | None = None) -> dict:
    """转换为响应格式。health_map: {provider: 指标快照};缺失则 health=None。"""
    health = (health_map or {}).get(source.provider)
    fuyao_operation = fuyao_rest.operation_for(source.type) if source.provider == "fuyao" else None
    business = fuyao_business.BY_OPERATION[fuyao_operation["id"]] if fuyao_operation else source.type
    ftshare_operation = ftshare_rest.operation_for(source.type) if source.provider == ftshare_rest.PROVIDER else None
    routing = call_order.metadata(source, TYPE_LABELS)
    return {
        "id": source.id,
        "name": source.name,
        "type": source.type,
        "type_label": ftshare_operation["group"] if ftshare_operation else TYPE_LABELS.get(business, business),
        "provider": source.provider,
        "provider_group": source_activation.provider_group(source.provider),
        "config": source.config or {},
        "enabled": source.enabled,
        "priority": call_order.FALLBACK_PROVIDERS.index(source.provider) if routing["mode"] == "fallback" else source.priority,
        "supports_batch": source.supports_batch or False,
        "test_symbols": source.test_symbols or [],
        "test_settings": source_test_settings.describe(source),
        "engine_attached": business in _ENGINE_ATTACHED_TYPES or business in fuyao_business.NATIVE,
        "ftshare_operation": ftshare_rest.describe(ftshare_operation) if ftshare_operation else None,
        "fuyao_operation": fuyao_operation,
        "business_type": business if fuyao_operation else None,
        "routing": routing,
        "workspace_path": f"/market-data/{business}" if business in fuyao_business.WORKSPACE_CAPABILITIES else None,
        "source_probe": source.type not in fuyao_business.DEFAULT_COMPETITORS or source.provider == "fuyao",
        "health": health,
        "is_orphan": _is_orphan(source.type, source.provider),
        "connection_status": (
            ("ready" if ftshare_configured else "authorization_required")
            if ftshare_operation and ftshare_configured is not None else
            ("ready" if fuyao_configured else "authorization_required")
            if source.provider == fuyao_credentials.PROVIDER and fuyao_configured is not None else None
        ),
    }


@router.get("")
def list_datasources(type: str | None = None, db: Session = Depends(get_db)):
    """获取数据源列表，可按类型筛选"""
    query = db.query(DataSource).filter(
        source_activation.provider_group_column().in_(source_activation.REGISTERED_PROVIDERS),
        DataSource.type.not_in(source_activation.RETIRED_TYPES),
    )
    if type:
        query = query.filter(DataSource.type == type)
    sources = query.order_by(DataSource.type, DataSource.id).all()
    from src.platform.marketdata.marketdata_client import get_market_data
    health_map = get_market_data().health()
    fuyao_configured = fuyao_credentials.configured(fuyao_credentials.read(db))
    ftshare_configured = provider_credentials.configured(provider_credentials.read(db, ftshare_rest.PROVIDER))
    return [_to_response(s, health_map, fuyao_configured, ftshare_configured) for s in sources]


def _require_fuyao_key(db: Session, provider: str, enabled: bool) -> None:
    if enabled and provider == fuyao_credentials.PROVIDER:
        try:
            fuyao_credentials.decrypt(fuyao_credentials.read(db))
        except fuyao_credentials.CredentialUnavailable as exc:
            raise api_error(409, "provider_key_required", str(exc)) from None


@router.get('/{source_id}/collection')
def collection_state(source_id: int, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    from src.modules.market.etf.free_sources import SPECS
    from src.modules.market.etf.models import EtfFetchState, EtfMeasurement
    source = db.get(DataSource, source_id)
    spec = SPECS.get((source.type, source.provider)) if source else None
    if not spec:
        raise api_error(404, 'datasource_not_found', '免费 ETF 数据源不存在')
    states = db.query(EtfFetchState).filter(EtfFetchState.resource == spec[0], EtfFetchState.source == source.provider)
    rows = states.order_by(EtfFetchState.checked_at.desc()).limit(limit).all()
    count = db.query(EtfMeasurement).filter(EtfMeasurement.resource == spec[0], EtfMeasurement.source == source.provider).count()
    enabled = bool(source.enabled and source_activation.provider_group(source.provider) not in source_activation.paused_providers(db))
    return {'enabled': enabled, 'observations': count, 'pending_retries': states.filter(EtfFetchState.status == 'error').count(),
            'items': [{key: getattr(row, key) for key in ('key', 'status', 'checked_at', 'retry_after', 'failures', 'error', 'record_count')} for row in rows]}


@router.get('/{source_id}/observations')
def source_observations(source_id: int, before_id: int | None = Query(None, ge=1),
                        limit: int = Query(20, ge=1, le=100), known_at: datetime | None = None,
                        db: Session = Depends(get_db)):
    from src.modules.market.etf.free_sources import SPECS
    from src.modules.market.etf.observations import read_observations

    source = db.get(DataSource, source_id)
    spec = SPECS.get((source.type, source.provider)) if source else None
    if not spec:
        raise api_error(404, 'datasource_not_found', '数据源不存在')
    if known_at and known_at.tzinfo is None:
        raise api_error(422, 'invalid_known_at', 'known_at 必须包含时区')
    return read_observations(db, resource=spec[0], source=source.provider,
                             before_id=before_id, limit=limit, known_at=known_at)


@router.get("/types")
def get_datasource_types():
    """获取数据源类型列表"""
    return [{"type": k, "label": v} for k, v in TYPE_LABELS.items()]


@router.post("/reset-to-seed")
def reset_datasources_to_seed(db: Session = Depends(get_db)):
    """恢复内置数据源默认值:补齐/删除孤儿并重置测试股票,保留用户配置与凭证。"""
    from server import reconcile_data_sources

    summary = reconcile_data_sources(db, reset_test_symbols=True)
    logger.info(f"数据源手动对账完成: {summary}")
    return summary


@router.get("/providers")
def get_provider_activation(db: Session = Depends(get_db)):
    return {"paused": sorted(source_activation.paused_providers(db))}


@router.put("/providers/{provider}")
def update_provider_activation(provider: str, data: DataSourceProviderUpdate, db: Session = Depends(get_db)):
    group = source_activation.provider_group(provider)
    if group not in source_activation.REGISTERED_PROVIDERS:
        raise api_error(404, "datasource_provider_not_found", "数据来源不存在。")
    source_activation.set_provider_enabled(db, group, data.enabled)
    from src.platform.marketdata.collectors.kline_collector import clear_kline_cache
    clear_kline_cache()
    return {"provider": group, "enabled": data.enabled}


@router.put("/providers/{provider}/endpoints")
def update_provider_endpoints(provider: str, data: DataSourceProviderUpdate, db: Session = Depends(get_db)):
    group = source_activation.provider_group(provider)
    if group not in source_activation.REGISTERED_PROVIDERS:
        raise api_error(404, "datasource_provider_not_found", "数据来源不存在。")
    if group in source_activation.paused_providers(db):
        raise api_error(409, "datasource_provider_paused", "请先打开该来源的总开关。")

    rows = db.query(DataSource.id, DataSource.type, DataSource.provider).filter(
        source_activation.provider_group_column() == group, DataSource.type.not_in(source_activation.RETIRED_TYPES),
    ).order_by(DataSource.id).all()
    if group == fuyao_credentials.PROVIDER:
        rows = [row for row in rows if row.provider == group and fuyao_rest.operation_for(row.type)]
    elif group == ftshare_rest.PROVIDER:
        rows = [row for row in rows if ftshare_rest.operation_for(row.type)]
    else:
        rows = [row for row in rows if not _is_orphan(row.type, row.provider)]

    ids = [row.id for row in rows]
    if ids:
        _require_fuyao_key(db, group, data.enabled)
        db.query(DataSource).filter(DataSource.id.in_(ids)).update({DataSource.enabled: data.enabled})
        db.commit()
        from src.platform.marketdata.collectors.kline_collector import clear_kline_cache
        clear_kline_cache()
    return {"provider": group, "enabled": data.enabled, "source_ids": ids}


@router.get("/{source_id}")
def get_datasource(source_id: int, db: Session = Depends(get_db)):
    """获取单个数据源"""
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source or not source_activation.supported_provider(source.provider):
        raise api_error(404, "datasource_not_found", "数据源不存在")
    return _to_response(source, fuyao_configured=fuyao_credentials.configured(fuyao_credentials.read(db)),
                        ftshare_configured=provider_credentials.configured(provider_credentials.read(db, ftshare_rest.PROVIDER)))


@router.post("")
def create_datasource(data: DataSourceCreate, db: Session = Depends(get_db)):
    """创建数据源"""
    if not source_activation.supported_provider(data.provider) or data.type in source_activation.RETIRED_TYPES:
        raise api_error(422, "datasource_provider_not_found", "数据来源不存在。")
    if data.provider in {ftshare_rest.PROVIDER, fuyao_credentials.PROVIDER} or data.type.startswith(
        (ftshare_rest.TYPE_PREFIX, fuyao_rest.TYPE_PREFIX)
    ):
        raise api_error(422, "datasource_managed_operation", "此供应商的接口由官方目录维护。")
    source = DataSource(
        name=data.name,
        type=data.type,
        provider=data.provider,
        config=data.config,
        enabled=data.enabled,
        priority=data.priority,
        supports_batch=data.supports_batch,
        test_symbols=data.test_symbols,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    logger.info(f"创建数据源: {source.name} ({source.provider})")
    return _to_response(source, fuyao_configured=fuyao_credentials.configured(fuyao_credentials.read(db)))


@router.put("/{source_id}")
def update_datasource(
    source_id: int, data: DataSourceUpdate, db: Session = Depends(get_db)
):
    """更新数据源"""
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source or not source_activation.supported_provider(source.provider):
        raise api_error(404, "datasource_not_found", "数据源不存在")

    changes = data.model_dump(exclude_unset=True)
    if "priority" in changes:
        raise api_error(409, "datasource_order_fixed", "仅 FTShare 与同花顺参与主备，调用顺序固定。")
    provider = changes.get("provider", source.provider)
    if not source_activation.supported_provider(provider) or changes.get("type", source.type) in source_activation.RETIRED_TYPES:
        raise api_error(422, "datasource_provider_not_found", "数据来源不存在。")
    if ftshare_rest.PROVIDER in (source.provider, provider) or (changes.get("type") or "").startswith(ftshare_rest.TYPE_PREFIX):
        operation = ftshare_rest.operation_for(source.type) if source.provider == ftshare_rest.PROVIDER else None
        if not operation or changes.keys() - {"enabled", "config"}:
            raise api_error(422, "ftshare_managed_operation", "FTShare 接口由官方目录维护。")
        if "config" in changes:
            try:
                changes["config"] = ftshare_rest.validate(operation, changes["config"])
            except ftshare_rest.InvalidQuery as exc:
                raise api_error(422, "ftshare_invalid_params", str(exc)) from None
    if fuyao_credentials.PROVIDER in (source.provider, provider) or (changes.get("type") or "").startswith(fuyao_rest.TYPE_PREFIX):
        operation = fuyao_rest.operation_for(source.type) if source.provider == fuyao_credentials.PROVIDER else None
        if not operation or changes.keys() - {"enabled", "config"}:
            raise api_error(422, "datasource_managed_operation", "同花顺接口由官方目录维护。")
        if "config" in changes:
            try:
                changes["config"] = {"params": fuyao_rest.saved_params(operation, changes["config"])}
            except fuyao_rest.InvalidQuery as exc:
                raise api_error(422, "fuyao_rest_invalid_params", str(exc)) from None
    if data.enabled or (provider != source.provider and changes.get("enabled", source.enabled)):
        _require_fuyao_key(db, provider, True)
    if "test_params" in changes:
        settings = source_test_settings.spec(provider, changes.get("type", source.type))
        if not settings:
            raise api_error(422, "datasource_test_params_invalid", "此来源不支持独立的测试参数设置。")
        try:
            params = source_test_settings.validate_params(settings["fields"], changes.pop("test_params"))
            if "test_symbols" in changes:
                changes["test_symbols"] = source_test_settings.normalize_symbols(settings["symbols"], changes["test_symbols"])
            changes["config"] = {**(changes.get("config") or source.config or {}), "test_params": params}
        except ValueError as exc:
            raise api_error(422, "datasource_test_params_invalid", str(exc)) from None
    for key, value in changes.items():
        setattr(source, key, value)

    db.commit()
    db.refresh(source)
    logger.info(f"更新数据源: {source.name}")
    if call_order.metadata(source, TYPE_LABELS)["key"] == "kline" and "enabled" in changes:
        from src.platform.marketdata.collectors.kline_collector import clear_kline_cache
        clear_kline_cache()
    return _to_response(source, fuyao_configured=fuyao_credentials.configured(fuyao_credentials.read(db)),
                        ftshare_configured=provider_credentials.configured(provider_credentials.read(db, ftshare_rest.PROVIDER)))


@router.delete("/{source_id}")
def delete_datasource(source_id: int, db: Session = Depends(get_db)):
    """删除数据源"""
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source or not source_activation.supported_provider(source.provider):
        raise api_error(404, "datasource_not_found", "数据源不存在")
    if source.provider in {ftshare_rest.PROVIDER, fuyao_credentials.PROVIDER}:
        raise api_error(409, "datasource_managed_operation", "此接口可停用，目录由服务商维护。")

    db.delete(source)
    db.commit()
    logger.info(f"删除数据源: {source.name}")
    return {"ok": True, "message": f"已删除 {source.name}"}


@router.post("/{source_id}/move")
def move_datasource(source_id: int, body: DataSourceMove, db: Session = Depends(get_db)):
    source = db.get(DataSource, source_id)
    if source is None or not source_activation.supported_provider(source.provider):
        raise api_error(404, "datasource_not_found", "数据源不存在")
    route = call_order.metadata(source, TYPE_LABELS)
    if route["mode"] != "fallback":
        raise api_error(409, "datasource_not_routable", "此接口不参与主备调度。")
    raise api_error(409, "datasource_order_fixed", "FTShare 优先，同花顺备用，调用顺序固定。")


@router.post("/{source_id}/test")
async def test_datasource(source_id: int, db: Session = Depends(get_db)):
    """测试数据源连接"""
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source or not source_activation.supported_provider(source.provider):
        raise api_error(404, "datasource_not_found", "数据源不存在")
    if not source_activation.supported_provider(source.provider) or source.type in source_activation.RETIRED_TYPES:
        raise api_error(409, "datasource_provider_retired", "此数据来源已停用。")
    if source_activation.provider_group(source.provider) in source_activation.paused_providers(db):
        raise api_error(409, "datasource_provider_paused", "请先打开该来源的总开关。")

    if source.provider == ftshare_rest.PROVIDER:
        from time import perf_counter
        from . import ftshare_rest as ftshare_api

        started = perf_counter()
        operation = source.type.removeprefix(ftshare_rest.TYPE_PREFIX)
        name, kind = source.name, source.type
        response = await ftshare_api.execute(db, operation, source.config or {})
        passed = ftshare_rest.successful(response)
        metadata = ftshare_rest.OPERATIONS[operation]
        return {"test_passed": passed, "source_name": name, "source_type": kind,
                "type_label": metadata["group"], "ftshare_tier": metadata["tier"],
                "provider": ftshare_rest.PROVIDER, "supports_batch": False, "test_symbols": [],
                "duration_ms": round((perf_counter() - started) * 1000), "count": 0, "items": None,
                "raw_response": response["response_json"], "http_status": response["http_status"],
                "business_code": response["business_code"], "error": None if passed else response["message"]}

    if source.provider == fuyao_credentials.PROVIDER:
        from time import perf_counter
        from . import fuyao_rest as fuyao_api

        operation = fuyao_rest.operation_for(source.type)
        if operation is None:
            raise api_error(404, "fuyao_rest_unknown_operation", "该接口不在同花顺目录中。")
        started = perf_counter()
        name, kind = source.name, source.type
        try:
            params = fuyao_rest.saved_params(operation, source.config or {})
        except fuyao_rest.InvalidQuery as exc:
            raise api_error(422, "fuyao_rest_invalid_params", str(exc)) from None
        response = await fuyao_api.execute(db, operation["id"], params)
        passed = 200 <= response["http_status"] < 300 and response["business_code"] == 0
        return {"test_passed": passed, "source_name": name, "source_type": kind,
                "type_label": TYPE_LABELS[fuyao_business.BY_OPERATION[operation["id"]]], "provider": "fuyao",
                "supports_batch": False, "test_symbols": [], "duration_ms": round((perf_counter() - started) * 1000),
                "count": 0, "raw_response": response["response_json"], "http_status": response["http_status"],
                "business_code": response["business_code"], "error": None if passed else "同花顺接口返回错误。"}

    from src.modules.market.data_collector import get_collector_manager

    manager = get_collector_manager()
    manager.clear_logs()

    result = await manager.test_source(source)

    # 不用 success / data 作为顶层字段,避免被 ResponseWrapperMiddleware 当成业务响应
    # 拆解后导致 metadata 丢失(详见 src/web/response.py:59 的特殊分支)。
    return {
        "test_passed": result.success,
        "source_name": source.name,
        "source_type": source.type,
        "type_label": TYPE_LABELS.get(source.type, source.type),
        "provider": source.provider,
        "supports_batch": source.supports_batch or False,
        "test_symbols": result.test_symbols,
        "test_params": result.test_params,
        "count": result.count,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "items": result.data,
        "errors": result.errors,
        "logs": manager.get_logs(),
    }
