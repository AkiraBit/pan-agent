"""The Tushare Pro HTTP protocol, sent through PanWatch's fixed relay."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
from cryptography.fernet import InvalidToken

from . import provider_credentials
from .fuyao_rest import InvalidQuery, MAX_QUERY_BYTES, MAX_RESPONSE_BYTES, _contains, _redact, query_params

PROVIDER = "tushare"
TYPE_PREFIX = "tushare:"
RELAY = "http://data.000666.site/dataapi"
CATALOG = json.loads(Path(__file__).with_name("tushare_rest_catalog.json").read_text(encoding="utf-8"))
OPERATIONS = {op["id"]: op for op in CATALOG["operations"]}
_ORDER = {api: index for index, api in enumerate(OPERATIONS)}


class CredentialUnavailable(RuntimeError):
    pass


class UpstreamError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status


def seeds():
    return [
        {"name": op["summary"], "type": TYPE_PREFIX + op["id"], "provider": PROVIDER,
         "config": {}, "enabled": True, "priority": 0, "supports_batch": False, "test_symbols": []}
        for op in OPERATIONS.values()
    ]


def operation_for(source_type: str):
    return OPERATIONS.get(source_type.removeprefix(TYPE_PREFIX)) if source_type.startswith(TYPE_PREFIX) else None


def describe(operation: dict) -> dict:
    return {**operation, "order": _ORDER[operation["id"]]}


def read_key(db):
    row = provider_credentials.read(db, PROVIDER)
    if not provider_credentials.configured(row):
        raise CredentialUnavailable("请先在设置 → 数据源服务商配置 Tushare API Key。")
    try:
        return provider_credentials.credential_cipher().decrypt(row.encrypted_key.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, OSError):
        raise CredentialUnavailable("无法读取 Tushare API Key，请重新保存。") from None


def validate(operation: dict, value: dict) -> dict:
    if not isinstance(value, dict) or value.keys() - {"params", "fields"}:
        raise InvalidQuery("Tushare 设置仅接受查询参数和返回字段。")
    supplied = value.get("params", {p["name"]: p["example"] for p in operation["parameters"] if "example" in p})
    if not isinstance(supplied, dict) or any(type(v) not in (str, int, type(None)) for v in supplied.values()):
        raise InvalidQuery("Tushare 查询参数必须是文档定义的标量。")
    params = query_params(operation, supplied)
    either = operation.get("require_any")
    if either and not any(name in params for name in either):
        raise InvalidQuery(f'{", ".join(either)} 至少填写一项。')
    for p in operation["parameters"]:
        if p["type"] == "integer" and p["name"] in params:
            params[p["name"]] = int(params[p["name"]])
    fields = value.get("fields", "")
    if not isinstance(fields, str) or len(fields) > MAX_QUERY_BYTES:
        raise InvalidQuery("返回字段必须是用逗号分隔的字段名。")
    names = [name.strip() for name in fields.split(",")] if fields.strip() else []
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names):
        raise InvalidQuery("返回字段必须是用逗号分隔的字段名。")
    return {"params": params, "fields": ",".join(names)}


def http_client():
    return httpx.AsyncClient(headers={"Accept": "application/json"}, follow_redirects=False, timeout=22)


async def query(operation_id: str, value: dict, key: str) -> dict:
    checked = validate(OPERATIONS[operation_id], value)
    try:
        async with asyncio.timeout(25), http_client() as client:
            async with client.stream("POST", RELAY, json={"api_name": operation_id, "token": key, **checked}) as response:
                status = response.status_code
                if 300 <= status < 400:
                    raise UpstreamError("tushare_redirect", "Tushare 中转返回了重定向。")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise UpstreamError("tushare_response_too_large", "Tushare 响应过大，请缩小查询范围。")
                    body.extend(chunk)
    except (TimeoutError, httpx.TimeoutException):
        raise UpstreamError("tushare_timeout", "Tushare 中转请求超时。", 504) from None
    except httpx.HTTPError:
        raise UpstreamError("tushare_unavailable", "无法连接 Tushare 中转。") from None

    try:
        raw = body.decode("utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        if _contains(data, key):
            data = _redact(data, key)
            raw = json.dumps(data, ensure_ascii=False)
    except (ValueError, RecursionError):
        if status < 400:
            raise UpstreamError("tushare_invalid_response", "Tushare 返回了无法解析的响应。") from None
        data, raw = {}, None
    code = data.get("code")
    result = data.get("data")
    items = result.get("items") if isinstance(result, dict) else None
    columns = result.get("fields") if isinstance(result, dict) else None
    if 200 <= status < 300 and code == 0 and (not isinstance(items, list) or not isinstance(columns, list)):
        raise UpstreamError("tushare_invalid_response", "Tushare 响应缺少字段或数据行。")
    message = data.get("msg")
    return {"http_status": status, "business_code": code if type(code) is int else None,
            "message": message if isinstance(message, str) else None, "response_json": raw,
            "row_count": len(items) if isinstance(items, list) else 0}


def successful(result: dict) -> bool:
    return 200 <= result["http_status"] < 300 and result["business_code"] == 0
