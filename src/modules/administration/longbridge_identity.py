"""Optional, verified account label for display; never used to authorize requests."""
import asyncio
import json
import re
import jwt

from .longbridge_mcp import ENDPOINTS, http_client, request_json


async def account_label(token: str, endpoint: str) -> str:
    if endpoint not in ENDPOINTS.values():
        return ""
    # Longbridge region-prefixed access tokens wrap a signed JWT. Opaque tokens
    # remain usable for MCP, but cannot supply a verified account label here.
    region = next((prefix for prefix in ("hk_", "sg_", "us_") if token.startswith(prefix)), "")
    raw = token[len(region):]
    try:
        header = jwt.get_unverified_header(raw)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            return ""
        async with asyncio.timeout(5), http_client() as client:
            keys = await request_json(client, "GET", endpoint.replace("mcp.", "openapi.") + "/.well-known/jwks.json")
        key = next(key for key in keys.get("keys", []) if key.get("kid") == header["kid"])
        # aud contains upstream API permission IDs, not this client's ID. This
        # is display metadata from our saved token, not an authentication check.
        claims = jwt.decode(raw, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"],
            issuer=["https://openapi.longbridge.cn", "https://openapi.longbridge.com"],
            options={"verify_aud": False, "require": ["sub", "exp", "iss", "iat"]}, leeway=30)
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject or len(subject) > 8192:
            return ""
        try:
            profile = json.loads(subject)
        except ValueError:
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        def field(*values):
            return next((v.strip() for v in values if isinstance(v, str) and 0 < len(v.strip()) <= 254
                         and not any(ord(c) < 32 for c in v)), "")
        email = field(claims.get("email"), profile.get("email"))
        name = field(claims.get("name"), profile.get("name"), profile.get("account_name"), profile.get("nickname"))
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return f"{email}({name})" if name else email
        if name:
            return name
        identifier = field(profile.get("account_no"), str(profile.get("member_id", ""))) if profile else subject
        if not identifier or identifier.startswith(("{", "[")):
            return ""
        suffix = identifier[-4:] if len(identifier) > 4 else ""
        return (region[:2].upper() + " · " if region else "") + "••••" + suffix
    except Exception:
        # Identity discovery must not destroy a working connection. No token,
        # claim, network response or exception detail is logged or returned.
        return ""
