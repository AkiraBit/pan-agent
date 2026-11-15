"""Host-owned Longbridge transport, saved market observations and source controls."""
import asyncio
import hashlib
import json
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from src.platform.persistence.database import SessionLocal
from src.platform.persistence.models import DataSource, LongbridgeObservation

TOOLS_BY_TYPE = {
    'quote': {'quote'}, 'kline': {'candlesticks'}, 'capital_flow': {'capital_distribution', 'capital_flow'},
    'fundamentals': {'static_info', 'calc_indexes', 'financial_report_snapshot'},
    'news': {'news', 'news_search'}, 'events': {'filings'}, 'dividend': {'dividend'},
    'etf_turnover': {'history_candlesticks_by_date'},
}
MARKET_TOOLS = set().union(*TOOLS_BY_TYPE.values())
_gate = threading.Lock()
_remote_transport = None


def configure_remote(transport):
    """The application composition root supplies its authenticated MCP port."""
    global _remote_transport
    _remote_transport = transport


def enabled(datatype, factory=None):
    with (factory or SessionLocal)() as db:
        return db.scalar(select(DataSource.id).where(DataSource.provider == 'longbridge',
            DataSource.type == datatype, DataSource.enabled.is_(True))) is not None


def unpack(result):
    if not isinstance(result, dict) or result.get('isError'):
        raise RuntimeError('Longbridge returned a tool error')
    value = result.get('structuredContent')
    if value is None:
        value = json.loads(''.join(x['text'] for x in result.get('content', []) if x.get('type') == 'text'))
    if isinstance(value, dict) and value.get('error_code'):
        code = value['error_code']
        raise RuntimeError('Longbridge rate limit' if code == 429002 else 'Longbridge data unavailable')
    if not isinstance(value, (dict, list)):
        raise ValueError('Invalid Longbridge market data')
    return value


def persist(tool, arguments, payload):
    args = json.dumps(arguments, sort_keys=True, ensure_ascii=False, allow_nan=False)
    checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    key = hashlib.sha256((tool + ':' + args).encode()).hexdigest()
    with SessionLocal() as db:
        last = db.scalar(select(LongbridgeObservation).where(LongbridgeObservation.request_key == key)
                         .order_by(LongbridgeObservation.id.desc()))
        if last is None or last.checksum != checksum:
            db.add(LongbridgeObservation(tool=tool, request_key=key, arguments=arguments, payload=payload,
                checksum=checksum, observed_at=datetime.now(timezone.utc).isoformat()))
            db.commit()


async def _remote(tool, arguments):
    if _remote_transport is None:
        raise RuntimeError('Longbridge transport is not configured')
    with SessionLocal() as db:
        return await _remote_transport(db, tool, arguments)


def query(tool, arguments):
    """Sync Engine port. Async consumers call in a worker, never on the event loop."""
    if tool not in MARKET_TOOLS:
        raise ValueError('Unsupported Longbridge market-data tool')
    with _gate:
        for attempt in range(3):
            try:
                value = unpack(asyncio.run(_remote(tool, arguments)))
                persist(tool, arguments, value)
                return value
            except RuntimeError as exc:
                if str(exc) != 'Longbridge rate limit' or attempt == 2:
                    raise
                time.sleep(2 ** attempt)
            except Exception as exc:
                detail = getattr(exc, 'detail', {})
                code = detail.get('code', '') if isinstance(detail, dict) else ''
                messages = {'mcp_authorization_required': 'Longbridge authorization required',
                            'mcp_connection_disabled': 'Longbridge connection disabled'}
                raise RuntimeError(messages.get(code, 'Longbridge market-data request failed')) from None
            finally:
                time.sleep(.2)
