"""Bounded Streamable HTTP tools client for fixed, built-in providers."""
import asyncio
import json

import httpx

from .longbridge_mcp import ENDPOINTS, fail, http_client


async def query(endpoint: str, token: str, tool: str | None, arguments: dict | None):
    if endpoint not in ENDPOINTS.values():
        raise fail("mcp_tool_not_allowed")
    return await streamable_query(endpoint, {"Authorization": f"Bearer {token}"}, tool, arguments,
                                  failure=fail)


async def streamable_query(endpoint, headers, tool, arguments, *, failure):
    headers = {**headers, "Accept": "application/json, text/event-stream"}
    sequence = 0
    async with http_client(headers=headers) as client:
        async def rpc(method, params=None, notification=False):
            nonlocal sequence
            sequence += 1
            payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            if not notification:
                payload["id"] = sequence
            async with client.stream("POST", endpoint, json=payload) as response:
                if response.status_code in (401, 403):
                    raise failure("mcp_authorization_required")
                if response.status_code == 429:
                    raise failure("mcp_rate_limited")
                response.raise_for_status()
                if session_id := response.headers.get("mcp-session-id"):
                    client.headers["Mcp-Session-Id"] = session_id
                if notification:
                    return None
                data, size, event = b"", 0, []
                streaming = "text/event-stream" in response.headers.get("content-type", "")
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1_048_576:
                        raise failure()
                    data += chunk
                    if streaming:
                        while b"\n" in data:
                            line, data = data.split(b"\n", 1)
                            line = line.rstrip(b"\r")
                            if line.startswith(b"data:"):
                                event.append(line[5:].lstrip())
                            elif not line and event:
                                message = json.loads(b"\n".join(event))
                                event = []
                                if isinstance(message, dict) and message.get("id") == sequence:
                                    return unpack(message)
                if not streaming:
                    message = json.loads(data)
                    if isinstance(message, dict) and message.get("id") == sequence:
                        return unpack(message)
                raise failure()

        def unpack(message):
            if "error" in message or not isinstance(message.get("result"), dict):
                raise failure()
            return message["result"]

        try:
            async with asyncio.timeout(30):
                initialized = await rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "PanWatch", "version": "1"}})
                version = initialized.get("protocolVersion")
                if version not in {"2025-03-26", "2025-06-18", "2025-11-25"}:
                    raise failure()
                client.headers["MCP-Protocol-Version"] = version
                await rpc("notifications/initialized", notification=True)
                if tool is not None:
                    return await rpc("tools/call", {"name": tool, "arguments": arguments or {}})
                found, cursor = [], None
                for _ in range(10):
                    page = await rpc("tools/list", {"cursor": cursor} if cursor else {})
                    if not isinstance(page.get("tools"), list):
                        raise failure()
                    found.extend(page["tools"])
                    cursor = page.get("nextCursor")
                    if cursor is not None and not isinstance(cursor, str):
                        raise failure()
                    if not cursor:
                        info = initialized.get("serverInfo")
                        server_version = info.get("version") if isinstance(info, dict) else None
                        return {"tools": found, "server_version": server_version[:128] if isinstance(server_version, str) else ""}
                raise failure()
        except (httpx.HTTPError, ValueError, TimeoutError, TypeError):
            raise failure() from None
        finally:
            if "Mcp-Session-Id" in client.headers:
                try:
                    await client.delete(endpoint, timeout=2)
                except httpx.HTTPError:
                    pass
