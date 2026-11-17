"""FTShare catalog and authenticated queries using the user's saved key."""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.platform.marketdata import ftshare_rest, provider_credentials, source_activation, source_calls
from src.platform.persistence.database import get_db
from src.platform.persistence.models import DataSource
from src.web.errors import api_error

from .mcp_connections import require_login

router = APIRouter(dependencies=[Depends(require_login)])


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    variant: int = 0
    params: dict[str, Any] = Field(max_length=32)


def _registered(db: Session):
    return db.query(DataSource).filter(DataSource.provider == ftshare_rest.PROVIDER)


async def execute(db: Session, operation: str, value: dict):
    try:
        prepared = source_calls.prepare(db, ftshare_rest.PROVIDER, operation, value)
        db.rollback()
        return await source_calls.send(prepared)
    except source_calls.CallError as exc:
        raise api_error(exc.status, exc.code, str(exc)) from None


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    rows = {row.type: row for row in _registered(db)}
    return {
        **ftshare_rest.CATALOG,
        "configured": provider_credentials.configured(provider_credentials.read(db, ftshare_rest.PROVIDER)),
        "paused": ftshare_rest.PROVIDER in source_activation.paused_providers(db),
        "operations": [
            {**ftshare_rest.describe(op), "enabled": bool(row and row.enabled), "settings": row.config if row else None}
            for op in ftshare_rest.OPERATIONS.values()
            for row in [rows.get(ftshare_rest.TYPE_PREFIX + op["id"])]
        ],
    }


@router.post("/query/{operation_id}")
async def query(operation_id: str, body: Query, db: Session = Depends(get_db)):
    return await execute(db, operation_id, body.model_dump())
