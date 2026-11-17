"""FTShare's documented Free and Basic REST operations."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from cryptography.fernet import InvalidToken

from . import provider_credentials
from .fuyao_rest import InvalidQuery, MAX_RESPONSE_BYTES, _contains, _redact, query_params

PROVIDER = "ftshare"
ORIGIN = "https://market.ft.tech/gateway"
CATALOG = json.loads(Path(__file__).with_name("ftshare_rest_catalog.json").read_text(encoding="utf-8"))
OPERATIONS = {op["id"]: op for op in CATALOG["operations"]}
TYPE_PREFIX = "ftshare:"


class CredentialUnavailable(RuntimeError):
    pass


class UpstreamError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 502):
        self.status, self.code = status, code
        super().__init__(message)


def seeds():
    return [
        {"name": op["summary"], "type": TYPE_PREFIX + op["id"], "provider": PROVIDER,
         "config": {}, "enabled": True, "priority": 0, "supports_batch": False, "test_symbols": []}
        for op in OPERATIONS.values()
    ]


def operation_for(source_type: str):
    return OPERATIONS.get(source_type.removeprefix(TYPE_PREFIX)) if source_type.startswith(TYPE_PREFIX) else None


def preset(variant: dict) -> dict[str, str]:
    values = variant["preset"]
    if field := variant.get("preset_today"):
        return {**values, field: datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")}
    return values


def describe(operation: dict) -> dict:
    return {**operation, "variants": [{**variant, "preset": preset(variant)} for variant in operation["variants"]]}


def read_key(db):
    row = provider_credentials.read(db, PROVIDER)
    if not provider_credentials.configured(row):
        raise CredentialUnavailable("请先在设置 → 数据源服务商配置 FTShare API Key。")
    try:
        return provider_credentials.credential_cipher().decrypt(row.encrypted_key.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, OSError):
        raise CredentialUnavailable("无法读取 FTShare API Key，请重新保存。") from None


def validate(operation: dict, value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - {"variant", "params"}:
        raise InvalidQuery("FTShare 设置仅接受官方路径选项和查询参数。")
    index = value.get("variant", 0)
    if type(index) is not int or not 0 <= index < len(operation["variants"]):
        raise InvalidQuery("无效的 FTShare 路径选项。")
    variant = operation["variants"][index]
    supplied = value["params"] if "params" in value else preset(variant)
    if not isinstance(supplied, dict) or any(type(v) not in (str, int, float, bool, type(None)) for v in supplied.values()):
        raise InvalidQuery("查询参数必须为文档定义的标量。")
    params = query_params(variant, supplied)
    for field in variant["parameters"]:
        name, fmt = field["name"], field.get("format")
        if fmt and name in params:
            try:
                python_format = "%Y%m%d" if fmt == "YYYYMMDD" else "%Y-%m-%d"
                pattern = r"[0-9]{8}" if fmt == "YYYYMMDD" else r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
                if not re.fullmatch(pattern, params[name]):
                    raise ValueError
                datetime.strptime(params[name], python_format)
            except ValueError:
                raise InvalidQuery(f"参数 {name} 必须为有效日期（{fmt}）。") from None
    for rule in variant["rules"]:
        count = sum(name in params for name in rule["fields"])
        kind = rule["kind"]
        if ((kind == "exactly_one" and count != 1)
                or (kind == "at_least_one" and count == 0)
                or (kind == "together" and 0 < count < len(rule["fields"]))
                or (kind == "exclusive" and count > 1)
                or (kind == "unless" and rule["fields"][0] not in params and count < len(rule["fields"]) - 1)
                or (kind == "same" and count == 2 and len({params[name] for name in rule["fields"]}) > 1)):
            instruction = {"exactly_one": "二选一", "at_least_one": "至少填写一项", "together": "需同时填写",
                           "exclusive": "不可同时填写", "same": "必须相同",
                           "unless": f"不填写 {rule['fields'][0]} 时，其余参数必填"}[kind]
            raise InvalidQuery(f'{", ".join(rule["fields"])}：{instruction}。')
    for start, end, sort_key in (("start_date", "end_date", lambda v: v.replace("-", "")),
                                 ("since_ts_millis", "until_ts_millis", int)):
        if start in params and end in params and sort_key(params[start]) > sort_key(params[end]):
            raise InvalidQuery(f"参数 {start} 不得晚于 {end}。")
    return {"variant": index, "params": params}


def http_client(key: str):
    return httpx.AsyncClient(headers={"FTSHARE_API_KEY": key, "Accept": "application/json",
                                      "Content-Type": "application/json"}, follow_redirects=False, timeout=22)


async def query(operation_id: str, value: dict, key: str) -> dict:
    operation = OPERATIONS[operation_id]
    checked = validate(operation, value)
    path = operation["variants"][checked["variant"]]["path"]
    try:
        async with asyncio.timeout(25), http_client(key) as client:
            async with client.stream(operation["method"], ORIGIN + path, params=checked["params"]) as response:
                status = response.status_code
                if 300 <= status < 400:
                    raise UpstreamError("ftshare_redirect", "FTShare 返回了重定向。")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise UpstreamError("ftshare_response_too_large", "FTShare 响应过大，请缩小查询范围或分页。")
                    body.extend(chunk)
    except (TimeoutError, httpx.TimeoutException):
        raise UpstreamError("ftshare_timeout", "FTShare API 请求超时。", 504) from None
    except httpx.HTTPError:
        raise UpstreamError("ftshare_unavailable", "无法连接 FTShare API。") from None

    try:
        raw = body.decode("utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, (dict, list)):
            raise ValueError
        if _contains(data, key):
            data = _redact(data, key)
            raw = json.dumps(data, ensure_ascii=False)
    except (ValueError, RecursionError):
        if status < 400:
            raise UpstreamError("ftshare_invalid_response", "FTShare 返回了无法解析的响应。") from None
        data, raw = {}, None
    code = data.get("code") if isinstance(data, dict) else None
    message = data.get("message") if isinstance(data, dict) else None
    return {"http_status": status, "business_code": code if type(code) is int else None,
            "message": message if isinstance(message, str) else None, "response_json": raw}


def successful(result: dict) -> bool:
    return result["http_status"] < 400 and result["business_code"] in (None, 0, 200)
