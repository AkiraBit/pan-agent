"""Official Tushare catalog and authenticated relay queries."""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.platform.marketdata import provider_credentials, source_activation, source_calls, tushare_rest
from src.platform.persistence.database import get_db
from src.platform.persistence.models import DataSource
from src.web.errors import api_error

from .mcp_connections import require_login

router = APIRouter(dependencies=[Depends(require_login)])


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    params: dict[str, Any] = Field(max_length=32)
    fields: str = Field(default="", max_length=16_384)


async def execute(db: Session, operation: str, value: dict):
    try:
        prepared = source_calls.prepare(db, tushare_rest.PROVIDER, operation, value)
        db.rollback()
        return await source_calls.send(prepared)
    except source_calls.CallError as exc:
        raise api_error(exc.status, exc.code, str(exc)) from None


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    rows = {row.type: row for row in db.query(DataSource).filter_by(provider=tushare_rest.PROVIDER)}
    return {
        "source": tushare_rest.CATALOG["source"],
        "configured": provider_credentials.configured(provider_credentials.read(db, tushare_rest.PROVIDER)),
        "paused": tushare_rest.PROVIDER in source_activation.paused_providers(db),
        "operations": [
            {**tushare_rest.describe(op), "enabled": bool(row and row.enabled), "settings": row.config if row else None}
            for op in tushare_rest.OPERATIONS.values()
            for row in [rows.get(tushare_rest.TYPE_PREFIX + op["id"])]
        ],
    }


@router.post("/query/{operation_id}")
async def query(operation_id: str, body: Query, db: Session = Depends(get_db)):
    return await execute(db, operation_id, body.model_dump())
