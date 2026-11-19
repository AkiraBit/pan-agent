"""Typed, provider-specific business reads through the existing Tushare relay."""
from __future__ import annotations

import asyncio
import json

from marketdata.fallback import SourceFailure

from . import source_calls, tushare_rest
from src.platform.persistence.database import SessionLocal


class TushareFailure(SourceFailure):
    def __init__(self, code, *, retry_after=0):
        super().__init__(f"Tushare {code}", retry_after=retry_after)
        self.code = code


def _prepare(operation, params, fields):
    with SessionLocal() as db:
        return source_calls.prepare(db, tushare_rest.PROVIDER, operation, {"params": params, "fields": fields})


async def rows(operation, params, fields=""):
    try:
        prepared = await asyncio.to_thread(_prepare, operation, params, fields)
        async with asyncio.timeout(8):
            reply = await source_calls.send(prepared)
    except TimeoutError:
        raise TushareFailure("unavailable") from None
    except source_calls.CallError as exc:
        if exc.code == "provider_key_required":
            raise TushareFailure("key_required") from None
        if exc.code in {"datasource_provider_paused", "datasource_operation_disabled"}:
            raise TushareFailure("source_disabled") from None
        raise TushareFailure("unavailable") from None

    status, code = reply["http_status"], reply["business_code"]
    message = (reply["message"] or "").lower()
    if status == 429 or code in {429, 42901, 40203} or any(word in message for word in ("频次", "限流", "请求过于频繁", "rate limit", "每秒", "每分钟", "每小时", "每天最多")):
        raise TushareFailure("rate_limited", retry_after=60)
    if status in {401, 403} or code in {401, 403, 40301, 2002} or any(
        word in message for word in ("权限", "积分", "permission", "未授权")
    ):
        raise TushareFailure("permission_required", retry_after=60)
    if not tushare_rest.successful(reply):
        if "token" in message:
            raise TushareFailure("key_required") from None
        raise TushareFailure("unavailable")

    try:
        data = json.loads(reply["response_json"])["data"]
        columns, items = data["fields"], data["items"]
        if not columns or not all(isinstance(col, str) for col in columns) or len(columns) != len(set(columns)):
            raise ValueError
        if not isinstance(items, list) or any(not isinstance(row, list) or len(row) != len(columns) for row in items):
            raise ValueError
        if not set(fields.split(",") if fields else ()) <= set(columns):
            raise ValueError
        return [dict(zip(columns, row, strict=True)) for row in items]
    except (ValueError, TypeError, KeyError):
        raise TushareFailure("unavailable") from None
