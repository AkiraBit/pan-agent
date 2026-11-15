"""Fixed public provider endpoints; no user URLs, credentials or browser state."""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

CN = ZoneInfo('Asia/Shanghai')
BOARD_URL = 'https://api.kanpanba.com/api/v1/etf/board'
DATES_URL = 'https://api.kanpanba.com/api/v1/etf/dates'
HOLDERS_URL = 'https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getFundHolder'
HOLDERS_PAGE = 'https://stock.finance.sina.com.cn/fundInfo/view/FundInfo_JJCYR.php'
INSTITUTIONS = {
    '中央汇金投资有限责任公司': 'huijin',
    '中央汇金资产管理有限责任公司': 'huijin',
    '中国证券金融股份有限公司': 'csf',
    '国新投资有限公司': 'guoxin',
    '中国国新控股有限责任公司': 'guoxin',
    '中国诚通控股集团有限公司': 'chengtong',
    '北京诚通金控投资有限公司': 'chengtong',
    '华夏-汇金资管单一资管计划': 'huijin',
    '易方达-汇金资管单一资管计划': 'huijin',
}


def today():
    return datetime.now(CN).date().isoformat()


def day(value):
    result = date.fromisoformat(value).isoformat()
    if result > today():
        raise ValueError('Future market date')
    return result


def finite(value, *, nonnegative=False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean measurement')
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError('Invalid measurement')
    return result


def validate_board(payload, requested=None):
    if not isinstance(payload, dict) or not isinstance(payload.get('etfs'), list) or not payload['etfs']:
        raise ValueError('Missing ETF observations')
    actual = day(payload['date'])
    if requested and actual != requested:
        raise ValueError('ETF date mismatch')
    codes = []
    for row in payload['etfs']:
        if not re.fullmatch(r'\d{6}', row['code']) or not row.get('name') or not row.get('index'):
            raise ValueError('Invalid ETF identity')
        codes.append(row['code'])
        for key in ('net', 'shares_delta', 'change_percent', 'net20'):
            finite(row.get(key))
        for key in ('close', 'scale', 'amount'):
            finite(row.get(key), nonnegative=True)
    covered = payload.get('covered')
    if len(set(codes)) != len(codes) or type(covered) is not int or not 0 <= covered <= len(codes):
        raise ValueError('Invalid or duplicate ETF coverage')
    for key in ('minutes', 'profile'):
        previous = ''
        for time, value in payload.get(key, []):
            if not re.fullmatch(r'(09|10|11|13|14|15):[0-5]\d', time) or time <= previous:
                raise ValueError('Invalid minute ordering')
            if finite(value, nonnegative=True) is None:
                raise ValueError('Missing minute measurement')
            previous = time
    for key in ('series', 'surges'):
        seen = set()
        for row in payload.get(key, []):
            if day(row['date']) > actual or row['date'] in seen:
                raise ValueError('Future or duplicate historical observation')
            seen.add(row['date'])
            finite(row.get('net'))
    # A report can legitimately contain gaps; never manufacture a zero net flow.
    if not payload.get('shares_published'):
        payload = {**payload, 'net': None,
                   'etfs': [{**r, 'net': None, 'shares_delta': None} for r in payload['etfs']]}
    return payload


async def request(url, params=None, *, text=False):
    async with httpx.AsyncClient(timeout=12, headers={'User-Agent': 'PanWatch/ETF market research', 'Accept': 'application/json,text/html'}, follow_redirects=False) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.content.decode('gb18030') if text else response.json()


async def board(requested=None):
    raw = await request(BOARD_URL, {'date': requested} if requested else None)
    return validate_board(raw, requested), raw


async def dates():
    values = await request(DATES_URL)
    if not isinstance(values, list) or not values:
        raise ValueError('Missing ETF dates')
    return sorted({day(value) for value in values}, reverse=True)


async def holding_periods(code):
    html = await request(HOLDERS_PAGE, {'symbol': code}, text=True)
    select = re.search(r'<select[^>]*id="tc_slt"[^>]*>(.*?)</select>', html, re.S)
    if not select:
        raise ValueError('Missing holder report dates')
    periods = sorted(set(re.findall(r'<option[^>]*value="(\d{4}-\d{2}-\d{2})"', select[1])), reverse=True)
    if not periods:
        raise ValueError('No holder reports')
    return [day(period) for period in periods]


async def holding_report(code, period):
    day(period)
    raw = await request(HOLDERS_URL, {'symbol': code, 'date': period})
    result = raw['result']
    rows = result.get('data')
    if result['status']['code'] != 0 or not isinstance(rows, list) or not rows:
        raise ValueError('Missing holder table')
    holders = []
    for row in rows:
        name = row['cyrmc'].strip()
        shares, ratio = finite(row['cyfe'], nonnegative=True), finite(row['zfeb'], nonnegative=True)
        if not name or shares is None or ratio is None or ratio > 100:
            raise ValueError('Invalid holder measurement')
        holders.append({'holder_name': name, 'shares': shares, 'ratio_percent': ratio,
                        'institution': INSTITUTIONS.get(name.replace('－', '-'))})
    if len({r['holder_name'] for r in holders}) != len(holders):
        raise ValueError('Duplicate holder')
    return {'code': code, 'report_date': period, 'holders': holders, 'raw': raw}


async def holding_reports(code):
    return [await holding_report(code, period) for period in (await holding_periods(code))[:2]]
