"""Load reviewed skill guidance through the normal, auditable tool runtime."""
from datetime import UTC, datetime

from pan_agent import ToolResult, ToolSpec
from sqlalchemy.orm import Session

from src.modules.administration import builtin_skills as skills


def register_builtin_skills(registry, session: Session, language: str):
    available = {item["id"]: item for item in skills.list_skills(session) if item["available"]}
    if not available:
        return
    bind = session.get_bind()
    english = language.startswith("en")

    async def load(_request, arguments):
        skill_id = arguments.get("skill_id")
        if skill_id not in available:
            return ToolResult.failure(summary="Unknown or unavailable built-in skill." if english else "此内置技能未启用或不可用。",
                                      error_code="skill_not_found")
        with Session(bind) as db:
            item = skills.status(db, skill_id)
            if not item["available"]:
                return ToolResult.failure(summary="Check the skill and its Longbridge MCP connection in MCP & Skills." if english else
                                          "请在 MCP & 技能中检查技能开关和长桥 MCP 连接。", error_code="skill_unavailable")
        return ToolResult.success(summary=skills.instructions(skill_id),
            data={"skill_id": skill_id, "version": item['version'], "upstream_revision": item['upstream_revision']},
            sources=[{"name": "PanWatch built-in skill", **({'url': item['source_url']} if item['source_url'].startswith('https://') else {})}],
            observed_at=datetime.now(UTC))

    choices = "; ".join(f"{key}: {item['title'][1 if english else 0]}" for key, item in available.items())
    registry.register(ToolSpec(name="load_builtin_skill",
        title="Load Longbridge skill" if english else "读取长桥技能",
        description=(("Before Longbridge queries, load the most relevant enabled workflow. Guidance only, not market data or permission. Available: " if english else
                      "处理长桥查询前，读取最符合问题的已启用技能流程。仅提供指引，不是行情结果，也不授予权限。当前可选：") + choices),
        input_schema={"type": "object", "required": ["skill_id"], "additionalProperties": False,
                      "properties": {"skill_id": {"type": "string", "enum": list(available)}}}), load)
