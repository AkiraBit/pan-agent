"""A real pull interface for an owner-configured, licensed auction gateway."""
from __future__ import annotations

import json
from datetime import datetime, time

import httpx
from pydantic import Field

from marketdata.short_term import TZ
from .schemas import Contract, Symbol


class AuctionQuote(Contract):
    symbol: Symbol
    source_time: datetime
    reference_price: float = Field(gt=0)
    pre_close: float = Field(gt=0)
    matched_volume_shares: float = Field(ge=0)
    unmatched_volume_shares: float = Field(ge=0)
    unmatched_side: str = Field(pattern='^(buy|sell|balanced)$')
    final: bool = False


async def read_auction(config, symbols, now):
    output = {'status': 'not_configured', 'provider': config.get('provider_name', 'licensed_gateway'),
              'observed_at': now.isoformat(), 'quotes': [], 'errors': []}
    if not config.get('enabled') or not config.get('endpoint'):
        return output
    local = now.astimezone(TZ)
    if not time(9, 15) <= local.time() < time(9, 30):
        return {**output, 'status': 'outside_auction'}
    headers = {'Accept': 'application/json'}
    if config.get('api_key'):
        headers['Authorization'] = 'Bearer ' + config['api_key']
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            async with client.stream('GET', config['endpoint'], params={'symbols': ','.join(symbols),
                                     'trade_date': local.date().isoformat()}, headers=headers) as response:
                response.raise_for_status()
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1_000_000:
                        raise ValueError('response_too_large')
        body = json.loads(raw)
        if body.get('schema_version') != 'auction.v1' or not isinstance(body.get('quotes'), list) or len(body['quotes']) > 100:
            raise ValueError('invalid_contract')
        seen = set()
        for item in body['quotes']:
            q = AuctionQuote.model_validate(item)
            if q.symbol not in symbols or q.symbol in seen or q.source_time.tzinfo is None:
                raise ValueError('invalid_identity_or_timestamp')
            if q.unmatched_side == 'balanced' and q.unmatched_volume_shares != 0:
                raise ValueError('inconsistent_unmatched_side')
            seen.add(q.symbol)
            stamp = q.source_time.astimezone(TZ)
            age = (now-q.source_time).total_seconds()
            valid = stamp.date() == local.date() and 0 <= age <= (300 if q.final else 15)
            valid = valid and (time(9, 25) <= stamp.time() < time(9, 30) if q.final else time(9, 15) <= stamp.time() < time(9, 25))
            if not valid:
                output['errors'].append({'symbol': q.symbol, 'reason': 'stale_or_wrong_phase'})
                continue
            data = q.model_dump(mode='json')
            data.update(auction_change_pct=(q.reference_price/q.pre_close-1)*100,
                        matched_amount_cny=q.reference_price*q.matched_volume_shares,
                        unmatched_ratio=((q.unmatched_volume_shares/q.matched_volume_shares) *
                                         (-1 if q.unmatched_side == 'sell' else 1)) if q.matched_volume_shares else None)
            output['quotes'].append(data)
        output['status'] = 'available' if len(output['quotes']) == len(symbols) else 'partial' if output['quotes'] else 'unavailable'
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        output['status'] = 'source_error'
    return output
