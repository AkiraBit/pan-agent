"""Shared credential for the Fuyao REST and MCP clients."""

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from src.platform.marketdata import provider_credentials
from src.platform.marketdata.provider_credentials import configured as configured
from src.platform.persistence.models import DataProviderCredential

PROVIDER = "fuyao"
ORIGIN = "https://fuyao.aicubes.cn"


class CredentialUnavailable(RuntimeError):
    pass


def read(db: Session) -> DataProviderCredential | None:
    return provider_credentials.read(db, PROVIDER)


def decrypt(row: DataProviderCredential | None) -> str:
    if not configured(row):
        raise CredentialUnavailable("请先在设置 → 数据源服务商配置同花顺 API Key。")
    try:
        return provider_credentials.credential_cipher().decrypt(row.encrypted_key.encode()).decode("ascii")
    except (InvalidToken, ValueError, OSError):
        raise CredentialUnavailable("无法读取同花顺 API Key，请在设置中重新保存。") from None


def get_api_key() -> str:
    from src.platform.persistence.database import SessionLocal

    with SessionLocal() as db:
        return decrypt(read(db))
