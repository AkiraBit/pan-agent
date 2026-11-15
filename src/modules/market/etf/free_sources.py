"""Public exchange / fund / quote HTTP adapters. Never execute remote JavaScript.

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
from xml.etree import ElementTree

import httpx

from . import sources

SSE = 'https://query.sse.com.cn/commonQuery.do'
SZSE = 'https://www.szse.cn/api/report/ShowReport/data'
NAV = 'https://fund.eastmoney.com/pingzhongdata/{code}.js'
PRICE = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
PCF_SZ = 'https://reportdocs.static.szse.cn/files/text/ETFDown/pcf_{code}_{day}.xml'
PCF_SH = 'https://query.sse.com.cn/etfDownload/downloadETF2Bulletin.do'
SPECS = {
    ('etf_shares', 'szse'): ('shares', '深交所 ETF 份额', ['159915', '159919']),
    ('etf_shares', 'sse'): ('shares', '上交所 ETF 份额', ['510300', '510050']),
    ('etf_nav', 'eastmoney'): ('nav', '天天基金 ETF 净值', ['510300', '159915']),
    ('etf_history', 'tencent'): ('price', '腾讯 ETF 历史行情', ['510300', '159915']),
    ('etf_pcf', 'szse'): ('pcf', '深交所 ETF 申赎清单', ['159915', '159845']),
    ('etf_pcf', 'sse'): ('pcf', '上交所 ETF 申赎清单', ['510300', '510050']),
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


def parse_szse(payload, requested_code, start, end, page):
    if not isinstance(payload, list) or len(payload) != 1:
        raise InvalidData('invalid_szse_envelope')
    result = payload[0]
    meta, raw = result.get('metadata', {}), result.get('data')
    if result.get('error') or not isinstance(raw, list) or meta.get('pageno') != page:
        raise InvalidData('invalid_szse_page')
    if meta.get('cols', {}).get('current_size') != '基金规模<br>(万份)':
        raise InvalidData('unexpected_share_unit')
    total, pages = meta.get('recordcount'), meta.get('pagecount')
    if type(total) is not int or type(pages) is not int or not 0 <= total <= 500 or not 0 <= pages <= 30:
        raise InvalidData('invalid_szse_pagination')
    rows = []
    for item in raw:
        actual_code, actual_day = code(item['fund_code']), day(item['size_date'])
        if actual_code != requested_code or not start <= actual_day <= end:
            raise InvalidData('unexpected_share_identity')
        rows.append({'code': actual_code, 'date': actual_day,
                     'shares': round(number(item['current_size'], positive=True) * 10000, 2)})
    return rows, total, pages


async def szse_shares(client, requested_code, start, end):
    requested_code = code(requested_code)
    if not requested_code.startswith('15') or (date.fromisoformat(end) - date.fromisoformat(start)).days > 179:
        raise InvalidData('unsupported_szse_range')
    rows, raw, page, expected = [], [], 1, None
    while True:
        params = {'SHOWTYPE': 'JSON', 'CATALOGID': 'scsj_fund_jjgm', 'jjlb': 'ETF',
                  'txtDm': requested_code, 'txtStart': start, 'txtEnd': end, 'PAGENO': page}
        payload = await client.json(SZSE, params, 'https://www.szse.cn/market/fund/volume/etf/index.html')
        items, total, pages = parse_szse(payload, requested_code, start, end, page)
        if expected is not None and expected != (total, pages):
            raise InvalidData('changing_szse_pagination')
        expected = (total, pages)
        rows.extend(items); raw.append(payload)
        if page >= pages:
            break
        if not items:
            raise InvalidData('empty_szse_page')
        page += 1
    result = unique(rows)
    if len(result) != total or len(result) != len(rows):
        raise InvalidData('incomplete_szse_pagination')
    return Batch('shares', 'szse', result, raw, SZSE, {'code': requested_code, 'start': start, 'end': end})


def parse_sse(payload, requested_day, codes):
    raw = payload.get('result')
    if payload.get('fieldErrors') or payload.get('actionErrors') or not isinstance(raw, list):
        raise InvalidData('invalid_sse_envelope')
    # The endpoint also exposes total/page metadata; never accept a truncated universe.
    total = payload.get('pageHelp', {}).get('total')
    if total is not None and int(total) != len(raw):
        raise InvalidData('incomplete_sse_pagination')
    rows = []
    for item in raw:
        actual_day = day(item['STAT_DATE'])
        if actual_day != requested_day:
            raise InvalidData('unexpected_share_date')
        actual_code = str(item['SEC_CODE']).strip()
        if actual_code in codes:
            rows.append({'code': code(actual_code), 'date': actual_day,
                         'shares': round(number(item['TOT_VOL'], positive=True) * 10000, 2)})
    return unique(rows)


async def sse_shares(client, requested_day, codes):
    params = {'sqlId': 'COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L', 'STAT_DATE': requested_day,
              'isPagination': 'true', 'pageHelp.pageSize': 10000, 'pageHelp.pageNo': 1}
    raw = await client.json(SSE, params, 'https://www.sse.com.cn/')
    return Batch('shares', 'sse', parse_sse(raw, requested_day, codes), raw, SSE, {'date': requested_day, 'codes': sorted(codes)})


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
    if requested_code != '000300':
        code(requested_code)
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > 500:
        raise InvalidData('unsupported_price_range')
    symbol = ('sz' if requested_code.startswith('15') else 'sh') + requested_code
    params = {'param': f'{symbol},day,{start},{end},640,'}
    raw = await client.json(PRICE, params)
    return Batch('price', 'tencent', parse_prices(raw, symbol, start, end), raw, PRICE, {'code': requested_code, 'start': start, 'end': end})


def parse_pcf(body, requested_code, expected_day=None):
    if re.search(br'<!\s*(DOCTYPE|ENTITY)', body, re.I):
        raise InvalidData('unsafe_xml_declaration')
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        raise InvalidData('invalid_pcf_xml') from None
    # XML uses different names at the two exchanges; nested component IDs must
    # never be confused with the root fund ID.
    header = {x.tag.split('}')[-1]: (x.text or '').strip() for x in root if not list(x)}
    def field(*names):
        return next((header[x] for x in names if header.get(x)), None)
    actual_code = field('SecurityID', 'FundInstrumentID', 'FundCode', 'ETFCode')
    if code(actual_code) != requested_code:
        raise InvalidData('unexpected_pcf_code')
    trading_day = day(field('TradingDay', 'TradingDate'))
    previous_day = day(field('PreTradingDay', 'PreTradingDate'))
    if previous_day >= trading_day or (expected_day and trading_day != expected_day):
        raise InvalidData('unexpected_pcf_date')
    value = number(field('NAV', 'NAVperShare'), positive=True)
    unit = number(field('CreationRedemptionUnit'), positive=True)
    components = []
    for element in root.iter():
        if element.tag.split('}')[-1] in {'Component', 'Stock'}:
            row = {x.tag.split('}')[-1]: (x.text or '').strip() for x in element}
            identifier = row.get('InstrumentID', row.get('UnderlyingSecurityID', ''))
            if not re.fullmatch(r'[A-Za-z0-9.]{1,20}', identifier):
                raise InvalidData('invalid_pcf_component')
            number(row.get('Quantity', row.get('ComponentShare')), nonnegative=True)
            components.append(row)
    if not components:
        raise InvalidData('missing_pcf_components')
    return {'code': requested_code, 'date': trading_day, 'nav_date': previous_day, 'nav': value,
            'creation_redemption_unit': unit, 'components': components, 'header': header}


async def pcf(client, provider, requested_code, requested_day=None):
    requested_code = code(requested_code)
    if provider == 'szse':
        if not requested_code.startswith('15') or not requested_day:
            raise InvalidData('unsupported_szse_pcf')
        url = PCF_SZ.format(code=requested_code, day=requested_day.replace('-', ''))
        body = await client.get(url)
    else:
        if not requested_code.startswith('5'):
            raise InvalidData('unsupported_sse_pcf')
        url = PCF_SH
        body = await client.get(url, {'fundCode': requested_code}, 'https://www.sse.com.cn/')
    row = parse_pcf(body, requested_code, requested_day if provider == 'szse' else None)
    return Batch('pcf', provider, [row], body.decode('utf-8-sig'), url,
                 {'code': requested_code, 'date': requested_day, 'mode': 'historical' if provider == 'szse' else 'latest'})
