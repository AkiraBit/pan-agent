"""Authenticated catalog and invocation API for all public Fuyao REST operations."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy import select

from src.platform.marketdata import fuyao_credentials, fuyao_rest, source_activation, source_calls
from src.platform.persistence.database import get_db
from src.platform.persistence.models import DataSource
from src.web.errors import api_error

from .mcp_connections import require_login

router = APIRouter(dependencies=[Depends(require_login)])


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=16)


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    provider = fuyao_credentials.PROVIDER
    paused = provider in source_activation.paused_providers(db)
    rows = {row.type: row for row in db.scalars(select(DataSource).where(DataSource.provider == provider))}
    return {**fuyao_rest.CATALOG, "configured": fuyao_credentials.configured(fuyao_credentials.read(db)), "paused": paused,
            "operations": [{**operation, "enabled": bool(row and row.enabled), "settings": row.config if row else None}
                           for operation in fuyao_rest.CATALOG["operations"]
                           for row in [rows.get(fuyao_rest.TYPE_PREFIX + operation["id"])]]}


async def execute(db: Session, operation_id: str, params: dict):
    try:
        prepared = source_calls.prepare(db, fuyao_credentials.PROVIDER, operation_id, params)
        db.rollback()
        return await source_calls.send(prepared)
    except source_calls.CallError as exc:
        raise api_error(exc.status, exc.code, str(exc)) from None


@router.post("/query/{operation_id}")
async def query(operation_id: str, body: Query, db: Session = Depends(get_db)):
    return await execute(db, operation_id, body.params)
