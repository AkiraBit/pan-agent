"""Built-in Longbridge connection. No user-supplied servers or executable packages."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import update
from sqlalchemy.orm import Session

from src.platform.persistence.models import MCPConnection
from src.platform.runtime.paths import get_data_dir
from src.web.errors import api_error

ENDPOINTS = {"cn": "https://mcp.longbridge.cn", "global": "https://mcp.longbridge.com"}
DOCS_URL = "https://open.longbridge.com/zh-CN/docs/mcp"
SCOPE = "account.read"
# Explicitly reviewed queries; upstream readOnlyHint is not an authorization policy.
READ_TOOLS = {
    "quote": ("行情快照", "Quotes"), "static_info": ("证券资料", "Security information"),
    "candlesticks": ("K 线", "Candlesticks"), "capital_flow": ("资金流向", "Capital flow"),
    "capital_distribution": ("资金分布", "Capital distribution"),
    "account_balance": ("账户余额", "Account balance"), "stock_positions": ("股票持仓", "Stock positions"),
    "trading_days": ("交易日历", "Trading calendar"),
    "screener_search": ("市场股票目录", "Market stock universe"),
    "market_temperature": ("市场温度", "Market temperature"),
    "history_market_temperature": ("历史市场温度", "Historical market temperature"),
}


def fail(code="mcp_connection_failed"):
    messages = {"mcp_authorization_required": "请先完成长桥授权，或重新授权。",
                "mcp_authorization_invalid": "授权已过期、已处理或不属于当前浏览器，请重新发起。",
                "mcp_connection_changed": "连接状态已改变，请刷新后重试。",
                "mcp_connection_disabled": "长桥 MCP 已停用。",
                "mcp_callback_invalid": "授权需要 HTTPS 访问地址；本机可使用 localhost 或 127.0.0.1。",
                "mcp_tool_not_allowed": "此工具未在内置查询工具范围内。",
                "mcp_storage_unavailable": "无法读取授权凭证，请恢复 MCP 加密密钥或断开后重新授权。"}
    return api_error(409 if code in messages else 502, code, messages.get(code, "长桥连接失败，请稍后重试。"))


def cipher() -> Fernet:
    """Keep the key outside the database and generic settings/configuration exports."""
    path = get_data_dir() / "mcp-credentials.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd, temporary = tempfile.mkstemp(prefix=".mcp-key-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(Fernet.generate_key())
            try:
                os.link(temporary, path)  # Atomic publication; never overwrite another worker's key.
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    return Fernet(path.read_bytes())


def seal(value: dict) -> str:
    return cipher().encrypt(json.dumps(value).encode()).decode()


def unseal(value: str) -> dict:
    if not value:
        return {}
    try:
        if not (get_data_dir() / "mcp-credentials.key").is_file():
            raise ValueError("key missing")
        return json.loads(cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError, OSError):
        raise fail("mcp_storage_unavailable") from None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read(db: Session) -> MCPConnection:
    db.expire_all()
    row = db.get(MCPConnection, "longbridge")
    if row is None:
        # Idempotent across first requests from different workers.
        from sqlalchemy.dialects.sqlite import insert
        db.execute(insert(MCPConnection).values(provider="longbridge").on_conflict_do_nothing())
        db.commit()
        row = db.get(MCPConnection, "longbridge")
    return row


def save(db: Session, version: int, *, require_idle_refresh=False, **values) -> None:
    statement = update(MCPConnection).where(MCPConnection.provider == "longbridge", MCPConnection.version == version)
    if require_idle_refresh:
        statement = statement.where(MCPConnection.refresh_until <= time.time())
    result = db.execute(statement.values(**values, version=version + 1),
        execution_options={"synchronize_session": False})
    db.commit()
    if result.rowcount != 1:
        raise fail("mcp_connection_changed")


def status(db: Session) -> dict:
    row = read(db)
    return {"id": "longbridge", "endpoint": ENDPOINTS[row.region], "region": row.region,
            "authorized": bool(row.credentials), "enabled": row.enabled,
            "pending": bool(row.pending) and row.pending_until > time.time(),
            "account_label": row.account_label, "connected_at": row.connected_at, "server_version": row.server_version,
            "tools": [{"name": t["name"], "title": READ_TOOLS[t["name"]],
                       "description": t.get("description") if isinstance(t.get("description"), str) else ""}
                      for t in json.loads(row.tools)],
            "checked_at": row.checked_at, "error_code": row.error_code, "docs_url": DOCS_URL}


def http_client(**kwargs):
    return httpx.AsyncClient(timeout=20, follow_redirects=False, **kwargs)


async def request_json(client, method, url, **kwargs):
    try:
        response = await client.request(method, url, **kwargs)
        if response.status_code in (401, 403):
            raise fail("mcp_authorization_required")
        if response.status_code == 400 and isinstance(response.json(), dict) and response.json().get("error") in {"invalid_grant", "invalid_token"}:
            raise fail("mcp_authorization_required")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("object required")
        return data
    except (httpx.HTTPError, ValueError):
        raise fail() from None


async def authorize(db: Session, region: str, origin: str, browser_key: str) -> dict:
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})) or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise fail("mcp_callback_invalid")
    redirect = f"{parsed.scheme}://{parsed.netloc}/integrations/mcp/callback"
    row = read(db)
    version = row.version
    endpoint = ENDPOINTS[region]
    async with http_client() as client:
        metadata = await request_json(client, "GET", endpoint + "/.well-known/oauth-authorization-server")
        # Discovery is restricted to the shipped provider, including its DCR endpoint.
        registration = endpoint.replace("mcp.", "openapi.") + "/oauth2/register"
        if metadata.get("authorization_endpoint") != endpoint + "/oauth2/authorize" or metadata.get("token_endpoint") != endpoint + "/oauth2/token" or metadata.get("registration_endpoint") != registration or "S256" not in metadata.get("code_challenge_methods_supported", []):
            raise fail()
        registered = await request_json(client, "POST", registration, json={
            "client_name": "PanWatch", "redirect_uris": [redirect], "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "scope": SCOPE})
    client_id = registered.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise fail()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    pending = {"state": digest(state), "browser": digest(browser_key), "verifier": verifier,
               "redirect_uri": redirect, "client_id": client_id, "region": region}
    save(db, version, pending=seal(pending), pending_until=int(time.time()) + 600)
    query = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect,
             "state": state, "scope": SCOPE, "resource": endpoint, "code_challenge_method": "S256",
             "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
    return {"authorization_url": endpoint + "/oauth2/authorize?" + urlencode(query), "state": state}


def tokens(data: dict, previous: dict) -> dict:
    if not isinstance(data.get("access_token"), str) or not data["access_token"] or str(data.get("token_type", "Bearer")).lower() != "bearer":
        raise fail()
    try:
        lifetime = max(1, min(int(data.get("expires_in", 3600)), 31536000))
    except (ValueError, TypeError):
        raise fail() from None
    return {**previous, "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or previous.get("refresh_token"),
            "expires_at": int(time.time()) + lifetime}


async def complete(db: Session, state: str, browser_key: str, code: str | None, error: str | None) -> dict:
    row = read(db)
    pending = unseal(row.pending)
    if row.pending_until < time.time() or not secrets.compare_digest(pending.get("state", ""), digest(state)) or not secrets.compare_digest(pending.get("browser", ""), digest(browser_key)):
        raise fail("mcp_authorization_invalid")
    version = row.version + 1
    save(db, row.version, pending="", pending_until=0)  # Consume before the external exchange.
    if error:
        return status(db)
    if not code:
        raise fail("mcp_authorization_invalid")
    endpoint = ENDPOINTS[pending["region"]]
    async with http_client() as client:
        data = await request_json(client, "POST", endpoint + "/oauth2/token", data={
            "grant_type": "authorization_code", "client_id": pending["client_id"], "code": code,
            "redirect_uri": pending["redirect_uri"], "code_verifier": pending["verifier"], "resource": endpoint})
    credential = tokens(data, {"client_id": pending["client_id"], "region": pending["region"]})
    from .longbridge_identity import account_label
    identity = await account_label(credential["access_token"], endpoint)
    save(db, version, credentials=seal(credential), region=pending["region"], enabled=False,
         tools="[]", checked_at=None, error_code="", refresh_until=0,
         connected_at=int(time.time()), account_label=identity, server_version="")
    return status(db)


async def access_token(db: Session, *, require_enabled=False) -> tuple[str, str, int]:
    for _ in range(40):
        row = read(db)
        if require_enabled and not row.enabled:
            raise fail("mcp_connection_disabled")
        credential, version = unseal(row.credentials), row.version
        if not credential:
            raise fail("mcp_authorization_required")
        endpoint = ENDPOINTS[row.region]
        if credential["expires_at"] > time.time() + 60:
            return endpoint, credential["access_token"], version
        if row.refresh_until > time.time():
            db.rollback()
            await asyncio.sleep(.1)
            continue
        lease = db.execute(update(MCPConnection).where(MCPConnection.provider == "longbridge",
            MCPConnection.version == version, MCPConnection.refresh_until <= time.time()).values(refresh_until=int(time.time()) + 30))
        db.commit()
        if lease.rowcount != 1:
            continue
        try:
            if not credential.get("refresh_token"):
                raise fail("mcp_authorization_required")
            # Keep OAuth renewal with the original issuer/client registration.
            # Only MCP traffic follows the user's selected network node.
            authorization_endpoint = ENDPOINTS[credential["region"]]
            async with http_client() as client:
                data = await request_json(client, "POST", authorization_endpoint + "/oauth2/token", data={
                    "grant_type": "refresh_token", "client_id": credential["client_id"],
                    "refresh_token": credential["refresh_token"], "resource": authorization_endpoint})
            renewed = tokens(data, credential)
            save(db, version, credentials=seal(renewed), refresh_until=0)
        except Exception as exc:
            values = {"refresh_until": 0}
            detail = getattr(exc, "detail", {})
            if isinstance(detail, dict) and detail.get("code") == "mcp_authorization_required":
                values.update(credentials="", enabled=False, tools="[]", account_label="", connected_at=None,
                              server_version="", error_code="mcp_authorization_required")
            db.execute(update(MCPConnection).where(MCPConnection.provider == "longbridge",
                MCPConnection.version == version).values(**values))
            db.commit()
            raise
    raise fail("mcp_connection_changed")


def discovery_values(result: dict) -> dict:
    approved = list({t["name"]: t for t in result["tools"] if isinstance(t, dict)
                     and isinstance(t.get("name"), str) and t["name"] in READ_TOOLS
                     and isinstance(t.get("inputSchema"), dict)
                     and t["inputSchema"].get("type") == "object"}.values())
    return {"tools": json.dumps(approved), "checked_at": int(time.time()), "error_code": "",
            "server_version": result["server_version"]}


async def change_region(db: Session, region: str) -> dict:
    from .mcp_transport import query
    row = read(db)
    if not row.credentials:
        raise fail("mcp_authorization_required")
    if row.region == region:
        return status(db)
    if row.pending and row.pending_until > time.time():
        raise fail("mcp_connection_changed")
    _, token, version = await access_token(db)
    # Probe before saving. A failed target must not revoke a working connection.
    result = await query(ENDPOINTS[region], token, None, None)
    # Do not interrupt token rotation or let a stale probe undo disconnect/disable.
    save(db, version, require_idle_refresh=True, region=region, **discovery_values(result))
    return status(db)


async def remote(db: Session, tool: str | None = None, arguments: dict | None = None):
    from .mcp_transport import query
    if tool is not None and tool not in READ_TOOLS:
        raise fail("mcp_tool_not_allowed")
    endpoint, token, version = await access_token(db, require_enabled=tool is not None)
    try:
        result = await query(endpoint, token, tool, arguments)
    except Exception as exc:
        detail = getattr(exc, "detail", {})
        error_code = detail.get("code", "mcp_connection_failed") if isinstance(detail, dict) else "mcp_connection_failed"
        values = {"error_code": error_code}
        if error_code == "mcp_authorization_required":
            values.update(credentials="", tools="[]", enabled=False, account_label="", connected_at=None, server_version="")
        save(db, version, **values)
        raise
    if tool is None:
        from .longbridge_identity import account_label
        identity = await account_label(token, endpoint) or read(db).account_label
        save(db, version, account_label=identity, **discovery_values(result))
        return status(db)
    if read(db).version != version:
        raise fail("mcp_connection_changed")
    return result


def disconnect(db: Session):
    row = read(db)
    save(db, row.version, credentials="", pending="", pending_until=0, enabled=False,
         tools="[]", error_code="", checked_at=None, refresh_until=0,
         connected_at=None, account_label="", server_version="")
    return status(db)
