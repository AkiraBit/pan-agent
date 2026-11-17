"""Public fund and quote HTTP adapters. Never execute remote JavaScript.

All money is CNY, shares are fund units, dates are exchange-local business dates.
A batch is validated before any of its rows can be committed.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from . import sources

NAV = 'https://fund.eastmoney.com/pingzhongdata/{code}.js'
PRICE = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
BENCHMARK_CODES = ('000001', '000300', '000688')
SPECS = {
    ('etf_nav', 'eastmoney'): ('nav', '天天基金 ETF 净值', ['510300', '159915']),
    ('etf_nav', 'fuyao'): ('nav', '同花顺基金净值', ['510300', '159915']),
    ('etf_history', 'tencent'): ('price', '腾讯 ETF 历史行情', ['510300', '159915']),
}
PARSER_VERSION = 'public-etf-v1'


class InvalidData(ValueError):
    pass


class Disabled(RuntimeError):
    pass


@dataclass
class Batch:
    resource: str
    source: str
    rows: list[dict]
    raw: object
    url: str
    request: dict


def number(value, *, positive=False, nonnegative=False):
    if value is None or isinstance(value, bool):
        raise InvalidData('missing_number')
    text = str(value).strip().replace('\u00a0', '').replace('，', ',')
    if ',' in text and not re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d+)?', text):
        raise InvalidData('invalid_number_grouping')
    try:
        result = Decimal(text.replace(',', ''))
    except InvalidOperation:
        raise InvalidData('invalid_number') from None
    if not result.is_finite() or abs(result) > Decimal('1e18') or (positive and result <= 0) or (nonnegative and result < 0):
        raise InvalidData('invalid_number_range')
    return float(result)


def code(value):
    result = str(value).strip()
    if not re.fullmatch(r'(?:15|5\d)\d{4}', result):
        raise InvalidData('invalid_etf_code')
    return result


def day(value):
    text = str(value).strip()
    if re.fullmatch(r'\d{8}', text):
        text = f'{text[:4]}-{text[4:6]}-{text[6:]}'
    try:
        result = date.fromisoformat(text).isoformat()
    except ValueError:
        raise InvalidData('invalid_business_date') from None
    if result > sources.today() or result < '1990-01-01':
        raise InvalidData('invalid_business_date')
    return result


def unique(rows):
    found = {}
    for row in rows:
        key = (row['code'], row['date'])
        if key in found and found[key] != row:
            raise InvalidData('conflicting_duplicate')
        found[key] = row
    return sorted(found.values(), key=lambda x: (x['code'], x['date']))


class Client:
    """Bounded responses, retries, rate limiting, and a live source-disable check."""
    def __init__(self, allowed=None):
        self.allowed = allowed
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), follow_redirects=False,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; PanWatch ETF research)', 'Accept': '*/*'})
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def get(self, url, params=None, referer=None):
        for attempt in range(3):
            if self.allowed is not None and not await asyncio.to_thread(self.allowed):
                raise Disabled('source_disabled')
            try:
                await asyncio.sleep(.35)
                async with self.client.stream('GET', url, params=params, headers={'Referer': referer or url}) as response:
                    response.raise_for_status()
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > 4_000_000:
                            raise InvalidData('response_too_large')
                        parts.append(part)
                    return b''.join(parts)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {408, 429, 500, 502, 503, 504}
                if not retryable or attempt == 2:
                    raise
                delay = 2 ** attempt
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        delay = min(15, max(delay, float(exc.response.headers.get('Retry-After', delay))))
                    except ValueError:
                        pass
                await asyncio.sleep(delay)

    async def json(self, *args, **kwargs):
        try:
            return json.loads(await self.get(*args, **kwargs))
        except (ValueError, UnicodeError):
            raise InvalidData('invalid_json_response') from None


def parse_nav(body, requested_code, start, end):
    text = body.decode('utf-8-sig')
    marker = re.search(r'\bvar\s+Data_netWorthTrend\s*=\s*', text)
    if not marker:
        raise InvalidData('missing_nav_series')
    identity = re.search(r'\bvar\s+fS_code\s*=\s*[\'"]([^\'"]+)', text)
    if not identity or code(identity[1]) != requested_code:
        raise InvalidData('unexpected_nav_code')
    try:
        raw, _ = json.JSONDecoder().raw_decode(text[marker.end():])
    except ValueError:
        raise InvalidData('invalid_nav_json') from None
    if not isinstance(raw, list) or len(raw) > 20000:
        raise InvalidData('invalid_nav_series')
    rows = []
    for item in raw:
        stamp = number(item['x'], positive=True)
        if stamp > 4e12:
            raise InvalidData('invalid_nav_timestamp')
        actual_day = day(datetime.fromtimestamp(stamp / 1000, sources.CN).date())
        if start <= actual_day <= end:
            rows.append({'code': requested_code, 'date': actual_day, 'nav': number(item['y'], positive=True),
                         'corporate_action': str(item.get('unitMoney') or '')[:500]})
    return unique(rows), raw


async def nav(client, requested_code, start, end):
    requested_code = code(requested_code)
    url = NAV.format(code=requested_code)
    rows, raw = parse_nav(await client.get(url, referer='https://fund.eastmoney.com/'), requested_code, start, end)
    return Batch('nav', 'eastmoney', rows, {'Data_netWorthTrend': raw}, url, {'code': requested_code, 'start': start, 'end': end})


async def fuyao_nav(requested_code, start, end):
    from src.platform.marketdata import fuyao_business, fuyao_rest

    requested_code = code(requested_code)
    thscode = requested_code + (".SZ" if requested_code.startswith("15") else ".SH")
    operation = "get_fund_performance_nav"
    args = {"thscode": thscode, "range": "twoyear", "nav_type": "unit"}
    payload = await fuyao_business.fetch(operation, args)
    if not isinstance(payload, dict) or not isinstance(payload.get("item"), list):
        raise InvalidData("invalid_nav_series")
    rows = []
    for item in payload["item"]:
        stamp = number(item.get("nav_date"), positive=True)
        actual_day = day(datetime.fromtimestamp(stamp / 1000, sources.CN).date())
        if start <= actual_day <= end:
            rows.append({"code": requested_code, "date": actual_day,
                         "nav": number(item.get("unit_nav"), positive=True), "corporate_action": ""})
    return Batch("nav", "fuyao", unique(rows), payload, fuyao_rest.OPERATIONS[operation]["docs_url"], args)


def parse_prices(payload, symbol, start, end):
    if payload.get('code') != 0:
        raise InvalidData('price_provider_error')
    raw = payload.get('data', {}).get(symbol, {}).get('day')
    if not isinstance(raw, list) or len(raw) >= 640:
        raise InvalidData('missing_or_truncated_unadjusted_prices')
    rows = []
    for item in raw:
        actual_day = day(item[0])
        if not start <= actual_day <= end:
            raise InvalidData('unexpected_price_date')
        op, close, high, low = [number(x, positive=True) for x in item[1:5]]
        volume = number(item[5], nonnegative=True)
        if low > min(op, close) or high < max(op, close) or low > high:
            raise InvalidData('invalid_ohlc')
        rows.append({'code': symbol[2:], 'date': actual_day, 'open': op, 'close': close,
                     'high': high, 'low': low, 'volume_lots': volume, 'adjustment': 'none'})
    return unique(rows)


async def prices(client, requested_code, start, end):
    if requested_code not in BENCHMARK_CODES:
        code(requested_code)
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > 500:
        raise InvalidData('unsupported_price_range')
    symbol = ('sz' if requested_code.startswith('15') else 'sh') + requested_code
    params = {'param': f'{symbol},day,{start},{end},640,'}
    raw = await client.json(PRICE, params)
    return Batch('price', 'tencent', parse_prices(raw, symbol, start, end), raw, PRICE, {'code': requested_code, 'start': start, 'end': end})
