"""Official Fuyao Streamable HTTP endpoints and read-only tool discovery.

The allowlist is the set of GET-backed tools in the official overview:
https://fuyao.aicubes.cn/docs/mcp/overview/
"""

import json
import time
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.platform.marketdata import fuyao_credentials as credentials
from src.platform.marketdata import source_calls
from src.platform.persistence.models import DataProviderCredential
from src.web.errors import api_error

from .mcp_transport import streamable_query

READ_TOOLS = json.loads(Path(__file__).with_name("fuyao_read_tools.json").read_text(encoding="utf-8"))
ENDPOINTS = {service: f"{credentials.ORIGIN}/mcp/{service}" for service in READ_TOOLS}


def failure(code="mcp_connection_failed"):
    status, message = {
        "mcp_authorization_required": (409, "同花顺 API Key 无效或无权访问该服务，请检查设置。"),
        "mcp_rate_limited": (429, "同花顺 MCP 调用频率受限，请稍后重试。"),
        "mcp_connection_changed": (409, "同花顺配置已改变，请刷新后重试。"),
        "mcp_test_required": (409, "请先检测此服务并获取可用的查询工具。"),
        "mcp_tool_not_allowed": (409, "同花顺 MCP 工具未启用或不在内置查询范围内。"),
    }.get(code, (502, "无法连接同花顺 MCP，请稍后重试。"))
    return api_error(status, code.replace("mcp_", "fuyao_mcp_", 1), message)


def tools_for(state: dict, service: str) -> dict:
    return {name: tool for name, tool in state.get("tools", {}).items() if name in READ_TOOLS[service]}


def status(db: Session) -> dict:
    row = credentials.read(db)
    states = row.mcp_services if row else {}
    return {"configured": credentials.configured(row), "services": [
        {"id": service, "endpoint": endpoint, "enabled": bool(state.get("enabled")),
         "checked_at": state.get("checked_at"),
         "tools": [{"name": name, "title": READ_TOOLS[service][name]} for name in tools_for(state, service)]}
        for service, endpoint in ENDPOINTS.items()
        for state in [states.get(service, {})]
    ]}


def _state(db: Session, service: str):
    if service not in ENDPOINTS:
        raise api_error(404, "fuyao_mcp_service_not_found", "同花顺 MCP 服务不存在。")
    row = credentials.read(db)
    try:
        key = credentials.decrypt(row)
    except credentials.CredentialUnavailable as exc:
        raise api_error(409, "provider_key_required", str(exc)) from None
    revision, states = row.revision, row.mcp_services
    db.rollback()  # Never hold a database transaction open during upstream requests.
    return key, revision, states


def _save(db: Session, revision: int, states: dict) -> dict:
    result = db.execute(update(DataProviderCredential).where(
        DataProviderCredential.provider == credentials.PROVIDER,
        DataProviderCredential.revision == revision,
    ).values(mcp_services=states, revision=revision + 1))
    if result.rowcount != 1:
        db.rollback()
        raise failure("mcp_connection_changed")
    db.commit()
    return status(db)


async def _query(service: str, key: str, name: str | None = None, arguments: dict | None = None):
    return await streamable_query(ENDPOINTS[service], {"X-api-key": key}, name, arguments, failure=failure)


async def test_service(db: Session, service: str) -> dict:
    key, revision, states = _state(db, service)
    result = await _query(service, key)
    tools = {}
    for item in result["tools"]:
        if not isinstance(item, dict):
            continue
        name, schema = item.get("name"), item.get("inputSchema")
        if (isinstance(name, str) and name in READ_TOOLS[service]
                and isinstance(schema, dict) and schema.get("type") == "object"):
            description = item.get("description")
            tools[name] = {"schema": schema, "description": description[:1400] if isinstance(description, str) else ""}
    if not tools:
        raise api_error(502, "fuyao_mcp_tools_missing", "此同花顺 MCP 服务未返回 PanWatch 支持的查询工具。")
    states[service] = {"enabled": bool(states.get(service, {}).get("enabled")),
                       "checked_at": int(time.time()), "tools": tools}
    return _save(db, revision, states)


def configure(db: Session, service: str, enabled: bool) -> dict:
    _, revision, states = _state(db, service)
    state = states.get(service, {})
    if enabled and not tools_for(state, service):
        raise failure("mcp_test_required")
    states[service] = {**state, "enabled": enabled}
    return _save(db, revision, states)


async def call(db: Session, service: str, name: str, arguments: dict):
    key, _, states = _state(db, service)
    state = states.get(service, {})
    if not state.get("enabled") or name not in tools_for(state, service):
        raise failure("mcp_tool_not_allowed")
    try:
        source_calls.require_enabled(db, credentials.PROVIDER, name)
    except source_calls.CallError as exc:
        raise api_error(exc.status, exc.code, str(exc)) from None
    finally:
        db.rollback()
    return await _query(service, key, name, arguments)
