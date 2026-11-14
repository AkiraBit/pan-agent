"""Pinned official sources and reviewed guidance for the built-in skill catalog."""
import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from src.platform.persistence.models import AppSettings, MCPConnection
from src.web.errors import api_error
from .longbridge_mcp import READ_TOOLS

SKILL_ID = "longbridge"
SETTING_KEY = "builtin_skill.longbridge.enabled"
VERSION = "1.0.0"
UPSTREAM_REVISION = "38900e9884027782c1f4e480b451d5f55a479d95"
SOURCE_URL = f"https://github.com/longbridge/skills/blob/{UPSTREAM_REVISION}/skills/longbridge/SKILL.md"
SKILLS_PATH = Path(__file__).with_name("skills")
SKILL_PATH = SKILLS_PATH / "longbridge" / "SKILL.md"


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict]:
    return {item["id"]: item for item in json.loads((SKILLS_PATH / "catalog.json").read_text(encoding="utf-8"))}


@lru_cache(maxsize=1)
def upstream() -> dict:
    # Official scripts are preserved as inert text in this bundle, never executable files.
    return json.loads((SKILLS_PATH / "longbridge-upstream.json").read_text(encoding="utf-8"))


def definition(skill_id: str) -> dict:
    if skill_id not in catalog():
        raise api_error(404, "skill_not_found", "此技能不在内置目录中。")
    return catalog()[skill_id]


def source(skill_id: str) -> dict:
    definition(skill_id)
    files = upstream()["files"]
    content = files[f"{skill_id}/SKILL.md"]
    version = re.search(r'^\s*version:\s*[\"\']?([\d.]+)', content.split("---", 2)[1], re.MULTILINE)
    return {"content": content, "upstream_version": version[1] if version else None,
            "bundled_file_count": sum(path.startswith(skill_id + "/") for path in files)}


def list_skills(db: Session) -> list[dict]:
    settings = {row.key: row.value == "true" for row in db.query(AppSettings).filter(AppSettings.key.like("builtin_skill.%"))}
    connection = db.get(MCPConnection, "longbridge")
    tools = {tool["name"] for tool in json.loads(connection.tools)} if connection else set()
    if not connection or not connection.credentials:
        dependency = "authorization_required"
    elif not connection.checked_at or not tools:
        dependency = "test_required"
    elif not connection.enabled:
        dependency = "mcp_disabled"
    else:
        dependency = "ready"
    items = []
    for skill_id, item in catalog().items():
        supported = bool(item["capabilities"])
        capabilities = [{**capability, "tools_present": set(capability["tools"]) <= tools}
                        for capability in item["capabilities"]]
        has_tools = any(capability["tools_present"] for capability in capabilities)
        state = "tools_missing" if supported and dependency == "ready" and not has_tools else dependency
        enabled = supported and settings.get(f"builtin_skill.{skill_id}.enabled", False)
        required = {tool for capability in capabilities for tool in capability["tools"]}
        original = source(skill_id)
        items.append({**item, "capabilities": capabilities, "support": "partial" if supported else "unsupported",
            "version": VERSION if supported else None, "upstream_revision": UPSTREAM_REVISION,
            "upstream_version": original["upstream_version"], "bundled_file_count": original["bundled_file_count"],
            "source_url": f"https://github.com/longbridge/skills/blob/{UPSTREAM_REVISION}/skills/{skill_id}/SKILL.md",
            "docs_url": "https://open.longbridge.com/zh-CN/skill", "enabled": enabled,
            "available": enabled and state == "ready", "connection_status": state,
            "tools": [{"name": name, "title": title, "present": name in tools} for name, title in READ_TOOLS.items() if name in required]})
    return items


def status(db: Session, skill_id: str = SKILL_ID) -> dict:
    definition(skill_id)
    return next(item for item in list_skills(db) if item["id"] == skill_id)


def configure(db: Session, enabled: bool, skill_id: str = SKILL_ID) -> dict:
    item = definition(skill_id)
    if enabled and not item["capabilities"]:
        raise api_error(409, "skill_not_supported", "此技能所需能力尚未接入，暂不能启用。")
    key = f"builtin_skill.{skill_id}.enabled"
    statement = insert(AppSettings).values(key=key, value="true" if enabled else "false")
    db.execute(statement.on_conflict_do_update(index_elements=[AppSettings.key], set_={"value": statement.excluded.value}))
    db.commit()
    db.expire_all()
    return status(db, skill_id)


def configure_supported(db: Session, enabled: bool) -> list[dict]:
    """Update all adapted Longbridge skills in one transaction, preserving MCP authorization."""
    values = [{"key": f"builtin_skill.{skill_id}.enabled", "value": "true" if enabled else "false"}
              for skill_id, item in catalog().items() if item["capabilities"]]
    if values:
        statement = insert(AppSettings).values(values)
        db.execute(statement.on_conflict_do_update(
            index_elements=[AppSettings.key], set_={"value": statement.excluded.value}))
        db.commit()
        db.expire_all()
    return list_skills(db)


def instructions(skill_id: str = SKILL_ID) -> str:
    item = definition(skill_id)
    if not item["capabilities"]:
        raise api_error(409, "skill_not_supported", "此技能所需能力尚未接入，暂不能启用。")
    specific = [f"\n## Selected skill: {skill_id} — {item['title'][1]}", item["description"][1],
        "\n### Supported workflow", *[f"{index}. {step[1]}" for index, step in enumerate(item["workflow"], 1)],
        "\n### Not supported by this skill", *[f"- {capability[1]}" for capability in item["unsupported_capabilities"]]]
    return SKILL_PATH.read_text(encoding="utf-8") + "\n".join(specific)
