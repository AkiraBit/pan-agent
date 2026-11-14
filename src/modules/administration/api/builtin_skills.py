"""Authenticated controls for shipped skills only."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.orm import Session

from src.modules.administration import builtin_skills as service
from src.platform.persistence.database import get_db
from .mcp_connections import require_login

router = APIRouter(dependencies=[Depends(require_login)])


class EnabledBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.get("")
def get_skills(db: Session = Depends(get_db)):
    return {"items": service.list_skills(db)}


@router.get("/{skill_id}/source")
def get_source(skill_id: str):
    return service.source(skill_id)


@router.put("/{skill_id}")
def configure(skill_id: str, body: EnabledBody, db: Session = Depends(get_db)):
    return service.configure(db, body.enabled, skill_id)
