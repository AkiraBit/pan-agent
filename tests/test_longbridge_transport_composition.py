import asyncio
from contextlib import contextmanager

import pytest

from src.platform.marketdata import longbridge


def test_application_injects_the_authenticated_mcp_transport(monkeypatch):
    from src.bootstrap import application  # noqa: F401
    from src.modules.administration import longbridge_mcp

    session = object()
    calls = []

    @contextmanager
    def factory():
        yield session

    async def remote(db, tool, arguments):
        calls.append((db, tool, arguments))
        return {'structuredContent': []}

    monkeypatch.setattr(longbridge, 'SessionLocal', factory)
    monkeypatch.setattr(longbridge_mcp, 'remote', remote)
    assert asyncio.run(longbridge._remote('quote', {'symbols': ['AAPL.US']})) == {'structuredContent': []}
    assert calls == [(session, 'quote', {'symbols': ['AAPL.US']})]


def test_unconfigured_transport_fails_without_opening_a_database(monkeypatch):
    monkeypatch.setattr(longbridge, '_remote_transport', None)
    with pytest.raises(RuntimeError, match='transport is not configured'):
        asyncio.run(longbridge._remote('quote', {}))
