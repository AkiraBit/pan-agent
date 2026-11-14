"""Authenticated management API for the shipped Longbridge connector."""
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.modules.administration import longbridge_mcp as service
from src.platform.persistence.database import get_db
from .auth import get_password_hash, security, verify_token
from src.web.errors import api_error


def require_login(db: Session = Depends(get_db), credentials=Depends(security)):
    # Broker authorization must never use the app's anonymous first-run exception.
    if not get_password_hash(db) or not credentials or not verify_token(credentials.credentials):
        raise api_error(401, "auth_required", "请先登录 PanWatch。")


router = APIRouter(dependencies=[Depends(require_login)])


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthorizeBody(StrictBody):
    region: Literal["cn", "global"] = "cn"
    browser_key: str = Field(min_length=32, max_length=128)


class CompleteBody(StrictBody):
    state: str = Field(min_length=32, max_length=128)
    browser_key: str = Field(min_length=32, max_length=128)
    code: str | None = Field(default=None, max_length=4096)
    error: str | None = Field(default=None, max_length=200)


class EnabledBody(StrictBody):
    enabled: bool


@router.get("")
def get_connections(db: Session = Depends(get_db)):
    return {"items": [service.status(db)]}


@router.post("/longbridge/authorize")
async def authorize(body: AuthorizeBody, request: Request, db: Session = Depends(get_db)):
    return await service.authorize(db, body.region, request.headers.get("origin") or str(request.base_url), body.browser_key)


@router.post("/longbridge/callback")
async def callback(body: CompleteBody, db: Session = Depends(get_db)):
    return await service.complete(db, **body.model_dump())


@router.delete("/longbridge/authorization")
def cancel(db: Session = Depends(get_db)):
    row = service.read(db)
    service.save(db, row.version, pending="", pending_until=0)
    return service.status(db)


@router.post("/longbridge/test")
async def test(db: Session = Depends(get_db)):
    return await service.remote(db)


@router.put("/longbridge")
def configure(body: EnabledBody, db: Session = Depends(get_db)):
    row = service.read(db)
    if body.enabled and (not row.credentials or not row.checked_at or row.tools == "[]"):
        raise service.fail("mcp_authorization_required")
    service.save(db, row.version, enabled=body.enabled)
    return service.status(db)


@router.delete("/longbridge")
def disconnect(db: Session = Depends(get_db)):
    return service.disconnect(db)
