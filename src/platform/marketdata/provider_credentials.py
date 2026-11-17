"""Encrypted credentials stored by data provider."""

from cryptography.fernet import InvalidToken
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from src.platform.persistence.local_cipher import local_cipher
from src.platform.persistence.models import DataProviderCredential
from src.platform.runtime.paths import get_data_dir


class CredentialStorageError(RuntimeError):
    pass


def credential_cipher(*, create: bool = False):
    return local_cipher(get_data_dir() / "data-provider-credentials.key", create=create)


def read(db: Session, provider: str) -> DataProviderCredential | None:
    return db.get(DataProviderCredential, provider, populate_existing=True)


def configured(row: DataProviderCredential | None) -> bool:
    return bool(row and row.encrypted_key)


def mask_key(key: str) -> str:
    prefix_length = len("ftshare_sk_") + 1 if key.startswith("ftshare_sk_") else 4
    # Keep at least eight characters hidden, even when a key is unusually short.
    if len(key) < prefix_length + 4 + 8:
        return "****"
    return f"{key[:prefix_length]}****{key[-4:]}"


def masked_key(row: DataProviderCredential | None) -> str | None:
    if not configured(row):
        return None
    try:
        key = credential_cipher().decrypt(row.encrypted_key.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, OSError):
        # The saved credential can still be replaced if local decryption fails.
        return "****"
    return mask_key(key)


def replace(db: Session, provider: str, key: str | None) -> None:
    encrypted = ""
    if key is not None:
        try:
            encrypted = credential_cipher(create=True).encrypt(key.encode("ascii")).decode("ascii")
        except (ValueError, OSError):
            raise CredentialStorageError from None
    # Replacement invalidates MCP discovery and activation tied to the old key.
    db.execute(insert(DataProviderCredential).values(provider=provider, encrypted_key=encrypted)
        .on_conflict_do_update(index_elements=["provider"], set_={
            "encrypted_key": encrypted, "mcp_services": {},
            "revision": DataProviderCredential.revision + 1,
        }))
    db.commit()
