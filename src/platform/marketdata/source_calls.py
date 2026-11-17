"""Explicit data-provider calls for consumers that understand the upstream response."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.platform.persistence.models import DataSource

from . import ftshare_rest, fuyao_credentials, fuyao_rest, source_activation, tushare_rest


class CallError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


@dataclass(frozen=True)
class PreparedCall:
    provider: str
    operation: str
    query: dict = field(repr=False)
    key: str = field(repr=False)


def _source_type(provider: str, operation: str) -> str:
    if provider == ftshare_rest.PROVIDER and operation in ftshare_rest.OPERATIONS:
        return ftshare_rest.TYPE_PREFIX + operation
    if provider == fuyao_credentials.PROVIDER and operation in fuyao_rest.OPERATIONS:
        return fuyao_rest.TYPE_PREFIX + operation
    if provider == tushare_rest.PROVIDER and operation in tushare_rest.OPERATIONS:
        return tushare_rest.TYPE_PREFIX + operation
    code = {"fuyao": "fuyao_rest_unknown_operation", "ftshare": "ftshare_unknown_operation",
            "tushare": "tushare_unknown_operation"}.get(
        provider, "datasource_provider_not_registered")
    raise CallError(404, code, "数据来源或接口不在已注册的调用目录中。")


def enabled_types(db: Session, provider: str) -> set[str]:
    return set(db.scalars(select(DataSource.type).where(DataSource.provider == provider, source_activation.active_source())))


def require_enabled(db: Session, provider: str, operation: str) -> None:
    kind = _source_type(provider, operation)
    if provider in source_activation.paused_providers(db):
        raise CallError(409, "datasource_provider_paused", "请先打开该来源的总开关。")
    if db.scalar(select(DataSource.id).where(
        DataSource.provider == provider, DataSource.type == kind, DataSource.enabled.is_(True),
    ).limit(1)) is None:
        raise CallError(409, "datasource_operation_disabled", "请先在「数据源」启用该接口。")


def prepare(db: Session, provider: str, operation: str, request: dict) -> PreparedCall:
    require_enabled(db, provider, operation)
    try:
        if provider == ftshare_rest.PROVIDER:
            params = ftshare_rest.validate(ftshare_rest.OPERATIONS[operation], request)
            key = ftshare_rest.read_key(db)
        elif provider == tushare_rest.PROVIDER:
            params = tushare_rest.validate(tushare_rest.OPERATIONS[operation], request)
            key = tushare_rest.read_key(db)
        else:
            params = fuyao_rest.query_params(fuyao_rest.OPERATIONS[operation], request)
            key = fuyao_credentials.decrypt(fuyao_credentials.read(db))
    except fuyao_rest.InvalidQuery as exc:
        code = {"ftshare": "ftshare_invalid_params", "tushare": "tushare_invalid_params",
                "fuyao": "fuyao_rest_invalid_params"}[provider]
        raise CallError(422, code, str(exc)) from None
    except (ftshare_rest.CredentialUnavailable, fuyao_credentials.CredentialUnavailable,
            tushare_rest.CredentialUnavailable) as exc:
        raise CallError(409, "provider_key_required", str(exc)) from None
    return PreparedCall(provider, operation, params, key)


async def send(call: PreparedCall) -> dict:
    try:
        if call.provider == ftshare_rest.PROVIDER:
            return await ftshare_rest.query(call.operation, call.query, call.key)
        if call.provider == tushare_rest.PROVIDER:
            return await tushare_rest.query(call.operation, call.query, call.key)
        return await fuyao_rest.query(call.operation, call.query, call.key)
    except (ftshare_rest.UpstreamError, tushare_rest.UpstreamError) as exc:
        raise CallError(exc.status, exc.code, str(exc)) from None
    except fuyao_rest.UpstreamError as exc:
        raise CallError(504 if exc.code == "fuyao_rest_timeout" else 502, exc.code, str(exc)) from None


async def call(provider: str, operation: str, *, params: dict, variant: int = 0, bind=None) -> dict:
    """Call exactly the requested source and operation; return its original JSON and transport status.

    A caller handles the provider's response fields. The gateway never changes
    providers, normalizes financial data, or accepts a caller-supplied URL or key.
    """
    from src.platform.persistence.database import SessionLocal

    if provider != ftshare_rest.PROVIDER and variant != 0:
        raise CallError(422, "datasource_invalid_variant", "该数据来源不支持路径选项。")
    request = {"params": params, "variant": variant} if provider == ftshare_rest.PROVIDER else params
    if provider == tushare_rest.PROVIDER:
        request = {"params": params}
    with (SessionLocal() if bind is None else Session(bind)) as db:
        prepared = prepare(db, provider, operation, request)
    return await send(prepared)
