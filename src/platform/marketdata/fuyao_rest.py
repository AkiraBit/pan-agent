"""Call the reviewed set of public Fuyao REST operations."""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .fuyao_credentials import ORIGIN

CATALOG = json.loads(Path(__file__).with_name("fuyao_rest_catalog.json").read_text(encoding="utf-8"))
OPERATIONS = {item["id"]: item for item in CATALOG["operations"]}
TYPE_PREFIX = "fuyao:"
MAX_QUERY_BYTES = 16_384
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class InvalidQuery(ValueError):
    pass


class UpstreamError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def operation_for(source_type: str):
    return OPERATIONS.get(source_type.removeprefix(TYPE_PREFIX)) if source_type.startswith(TYPE_PREFIX) else None


def example_params(operation: dict) -> dict:
    now = datetime.now(timezone.utc)
    return {p["name"]: int((now - timedelta(days=p["example_days_ago"])).timestamp() * 1000)
            if "example_days_ago" in p else p["example"] for p in operation["parameters"]
            if "example" in p or "example_days_ago" in p}


def saved_params(operation: dict, settings: dict) -> dict[str, str]:
    if not isinstance(settings, dict) or settings.keys() - {"params"}:
        raise InvalidQuery("同花顺设置仅接受官方接口的查询参数。")
    return query_params(operation, settings.get("params", example_params(operation)))


def query_params(operation: dict, supplied: dict) -> dict[str, str]:
    if not isinstance(supplied, dict):
        raise InvalidQuery("查询参数必须为对象。")
    parameters = {param["name"]: param for param in operation["parameters"]}
    if supplied.keys() - parameters.keys():
        raise InvalidQuery("包含官方接口未定义的参数。")
    result = {}
    for name, param in parameters.items():
        value = supplied.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if param["required"]:
                raise InvalidQuery(f"缺少必填参数 {name}。")
            continue
        kind = param["type"]
        if kind == "string":
            if not isinstance(value, str) or ("enum" in param and value not in param["enum"]):
                raise InvalidQuery(f"参数 {name} 不符合文档定义。")
            result[name] = value
        elif kind == "boolean":
            if type(value) is bool:
                value = str(value).lower()
            if value not in ("true", "false"):
                raise InvalidQuery(f"参数 {name} 必须为 true 或 false。")
            result[name] = value
        else:
            value = str(value)
            pattern = r"[+-]?[0-9]+" if kind == "integer" else r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
            if len(value) > 128 or not re.fullmatch(pattern, value):
                raise InvalidQuery(f"参数 {name} 必须为{'整数' if kind == 'integer' else '数字'}。")
            try:
                number = Decimal(value)
            except InvalidOperation:
                raise InvalidQuery(f"参数 {name} 超出数值范围。") from None
            if (("minimum" in param and number < Decimal(str(param["minimum"])))
                    or ("maximum" in param and number > Decimal(str(param["maximum"])))):
                raise InvalidQuery(f"参数 {name} 超出文档规定的范围。")
            result[name] = value
    try:
        if len(urlencode(result)) > MAX_QUERY_BYTES:
            raise InvalidQuery("查询参数过长。")
    except UnicodeEncodeError:
        raise InvalidQuery("查询参数包含无效字符。") from None
    return result


def http_client(key: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"X-api-key": key, "Accept": "application/json"},
                             follow_redirects=False, timeout=22)


def _redact(value, secret: str):
    """Only needed if an upstream response echoes the credential."""
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(name, secret): _redact(item, secret) for name, item in value.items()}
    return value


def _contains(value, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, list):
        return any(_contains(item, secret) for item in value)
    if isinstance(value, dict):
        return any(secret in name or _contains(item, secret) for name, item in value.items())
    return False


async def query(operation_id: str, params: dict[str, str], key: str) -> dict:
    # The client can select an operation, never its host, method, path or headers.
    operation = OPERATIONS[operation_id]
    try:
        async with asyncio.timeout(25), http_client(key) as client:
            async with client.stream("GET", ORIGIN + operation["path"], params=params) as response:
                status = response.status_code
                if 300 <= status < 400:
                    raise UpstreamError("fuyao_rest_redirect", "同花顺返回了重定向。")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise UpstreamError("fuyao_rest_too_large", "同花顺响应过大，请缩小查询范围或分页。")
                    body.extend(chunk)
    except (TimeoutError, httpx.TimeoutException):
        raise UpstreamError("fuyao_rest_timeout", "同花顺 API 请求超时。") from None
    except httpx.HTTPError:
        raise UpstreamError("fuyao_rest_unavailable", "无法连接同花顺 API。") from None

    try:
        raw = body.decode("utf-8-sig")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object")
        code = parsed.get("code")
        request_id = parsed.get("request_id")
        if _contains(parsed, key):
            # Keep the original numeric text for normal responses (JavaScript cannot
            # represent all upstream int64 IDs). Re-encode only for secret redaction.
            raw = json.dumps(_redact(parsed, key), ensure_ascii=True)
        return {"http_status": status, "business_code": code if type(code) is int else None,
                "request_id": _redact(request_id, key) if isinstance(request_id, str) else None,
                "response_json": raw}
    except (ValueError, RecursionError):
        if status in (401, 403, 429):
            return {"http_status": status, "business_code": None, "request_id": None, "response_json": None}
        raise UpstreamError("fuyao_rest_invalid_response", "同花顺返回了无法解析的响应。") from None
