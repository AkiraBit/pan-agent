import asyncio
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from src.modules.administration import longbridge_identity as identity


@pytest.fixture
def signing(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid='test-key', alg='RS256', use='sig')
    calls = []
    def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://openapi.longbridge.cn/.well-known/jwks.json'
        assert 'authorization' not in request.headers
        return httpx.Response(200, json={'keys': [public]})
    monkeypatch.setattr(identity, 'http_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    claims = {'iss': 'https://openapi.longbridge.cn', 'sub': 'synthetic-account-1234',
              'aud': ['opaque-permission'], 'exp': int(time.time()) + 3600, 'iat': int(time.time())}
    def token(**overrides):
        return 'hk_' + jwt.encode({**claims, **overrides}, key, algorithm='RS256', headers={'kid': 'test-key'})
    return token, calls


def test_account_label_is_signature_verified_masked_and_not_a_client_identifier(signing):
    token, calls = signing
    assert asyncio.run(identity.account_label(token(), 'https://mcp.longbridge.cn')) == 'HK · ••••1234'
    assert len(calls) == 1


def test_nested_longbridge_subject_uses_account_number_not_json_suffix(signing):
    token, _ = signing
    subject = json.dumps({'client_id': 'not-the-account', 'member_id': 321321,
                          'account_no': 'HK001234', 'ms_id': 'unrelated40'})
    assert asyncio.run(identity.account_label(token(sub=subject), 'https://mcp.longbridge.cn')) == 'HK · ••••1234'


@pytest.mark.parametrize('claims, expected', [
    ({'email': 'demo@example.com', 'name': 'Demo Account'}, 'demo@example.com(Demo Account)'),
    ({'sub': json.dumps({'email': 'demo@example.com', 'account_name': 'Demo Account'})}, 'demo@example.com(Demo Account)'),
    ({'email': 'demo@example.com'}, 'demo@example.com'),
    ({'email': 'invalid-email'}, 'HK · ••••1234'),
    ({'sub': json.dumps({'client_id': 'not-the-account'})}, ''),
])
def test_email_and_account_name_are_used_only_when_provided(signing, claims, expected):
    token, _ = signing
    assert asyncio.run(identity.account_label(token(**claims), 'https://mcp.longbridge.cn')) == expected


@pytest.mark.parametrize('overrides', [{'iss': 'https://attacker.example'}, {'exp': 1}, {'sub': ''}])
def test_invalid_identity_does_not_produce_a_label(signing, overrides):
    token, _ = signing
    assert asyncio.run(identity.account_label(token(**overrides), 'https://mcp.longbridge.cn')) == ''


def test_forged_and_opaque_tokens_cannot_supply_an_account_label(signing):
    token, _ = signing
    raw = token()[3:]
    header, payload, signature = raw.split('.')
    forged = 'hk_' + header + '.' + payload + '.' + ('A' if signature[0] != 'A' else 'B') + signature[1:]
    assert asyncio.run(identity.account_label(forged, 'https://mcp.longbridge.cn')) == ''
    assert asyncio.run(identity.account_label('opaque-token', 'https://mcp.longbridge.cn')) == ''
    assert asyncio.run(identity.account_label(token(), 'https://attacker.example')) == ''
