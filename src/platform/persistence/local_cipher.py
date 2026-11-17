"""Store a local encryption key beside the database, with atomic creation."""

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet


def local_cipher(path: Path, *, create: bool = False) -> Fernet:
    if create and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(Fernet.generate_key())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    return Fernet(path.read_bytes())
