"""Bounded, auditable A-share daily prices with an explicit adjustment basis.

Tencent's ``day`` fallback is not an adjustment declaration. When it occurs,
request unadjusted prices explicitly and divide by Sina's dated qfq factors.
These are provider conventions, never exchange-certified reference prices.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
import re

from marketdata.http import market_get
from marketdata.short_term import TZ

TENCENT_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
SINA_FACTOR_URL = 'https://finance.sina.com.cn/realstock/company/{}/qfq.js'


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def parse_rows(values, today):
    if not isinstance(values, list) or not 1 <= len(values) <= 101:
        raise ValueError('history_unavailable')
    rows = []
    for value in values:
        if not isinstance(value, list) or len(value) < 6:
            raise ValueError('invalid_history_row')
        day = date.fromisoformat(value[0]).isoformat()
        if day > today or (rows and day <= rows[-1]['date']):
            raise ValueError('invalid_history_date')
        prices = [float(v) for v in value[1:5]]
        volume = float(value[5])
        if not all(math.isfinite(p) and p > 0 for p in prices) or not math.isfinite(volume) or volume < 0:
            raise ValueError('invalid_history_price')
        opening, close, high, low = prices
        if low > min(opening, close) or high < max(opening, close):
            raise ValueError('invalid_history_ohlc')
        rows.append(dict(date=day, open=opening, close=close, high=high, low=low, volume_lots=volume))
    return rows


def parse_factors(text, code, today):
    if not isinstance(text, str) or len(text.encode()) > 200_000:
        raise ValueError('factor_source_unavailable')
    # Parse data, never execute the downloaded JavaScript or its trailing comment.
    match = re.match(r'\s*var\s+' + re.escape(code) + r'qfq\s*=\s*', text)
    if not match:
        raise ValueError('factor_subject_mismatch')
    payload, end = json.JSONDecoder().raw_decode(text[match.end():])
    tail = text[match.end()+end:].strip().lstrip(';').strip()
    if tail and not re.fullmatch(r'/\*.*\*/', tail, re.S):
        raise ValueError('factor_schema_invalid')
    values = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(values, list) or not 1 <= len(values) <= 2000 or type(payload.get('total')) is not int or payload['total'] != len(values):
        raise ValueError('factor_coverage_incomplete')
    factors = {}
    for value in values:
        day = date.fromisoformat(value['d']).isoformat()
        if isinstance(value['f'], bool):
            raise ValueError('factor_value_invalid')
        factor = Decimal(value['f'])
        if day > today or day in factors or not factor.is_finite() or factor <= 0:
            raise ValueError('factor_value_invalid')
        factors[day] = str(factor)
    return [{'date': d, 'factor': f} for d, f in sorted(factors.items())]


def apply_factors(rows, factors):
    dates = [f['date'] for f in factors]
    adjusted, inputs = [], []
    for row in rows:
        index = bisect_right(dates, row['date']) - 1
        if index < 0:
            raise ValueError('factor_history_incomplete')
        record = factors[index]
        factor = Decimal(record['factor'])
        values = {k: float(Decimal(str(row[k])) / factor) for k in ('open', 'close', 'high', 'low')}
        if not all(math.isfinite(v) and v > 0 for v in values.values()):
            raise ValueError('adjusted_price_invalid')
        adjusted.append({**row, **values})
        inputs.append({'date': row['date'], 'factor_date': record['date'], 'factor': record['factor'],
                       'raw_close': row['close'], 'adjusted_close': values['close']})
    return adjusted, inputs


def adjusted_daily_series(symbol, count=80):
    code = symbol if re.fullmatch(r'(?:sh|sz)\d{6}', symbol) else symbol[-2:].lower() + symbol[:6]
    if not re.fullmatch(r'(?:sh|sz)\d{6}', code):
        return {'rows': [], 'status': 'invalid_symbol'}
    count = min(max(int(count), 1), 100)
    now = datetime.now(TZ)
    result = {'rows': [], 'status': 'unavailable', 'source': 'tencent', 'adjustment': 'unverified',
              'observed_at': now.isoformat(), 'price_basis': {'status': 'unverified'}, 'raw': {}}

    def request(mode):
        params = {'param': f'{code},day,,,{count},{mode}'}
        raw = market_get(TENCENT_URL, host_key='sentiment.daily', params=params, parse='json',
                         timeout=8, total_timeout=10, retries=0, min_interval_s=.1)
        data = raw.get('data', {}).get(code) if isinstance(raw, dict) and raw.get('code', 0) == 0 and isinstance(raw.get('data'), dict) else None
        if not isinstance(data, dict):
            raise ValueError('history_subject_or_source_unavailable')
        result['raw']['qfq_request' if mode else 'unadjusted_request'] = {'url': TENCENT_URL, 'params': params, 'response': raw}
        return data

    try:
        data = request('qfq')
        values = data.get('qfqday') or data.get('day')
        rows = parse_rows(values, now.date().isoformat())[-count:]
        if data.get('qfqday'):
            basis = {'status': 'provider_basis', 'method': 'tencent_qfq_field', 'price_source_url': TENCENT_URL,
                     'response_hash': fingerprint(result['raw']['qfq_request']['response'])}
        elif re.fullmatch(r'sh000\d{3}|sz399\d{3}', code):
            result.update(rows=rows, status='available', adjustment='index_unadjusted')
            return result
        else:
            # Do not apply factors to the ambiguous day data from a qfq request.
            raw_data = request('')
            raw_rows = parse_rows(raw_data.get('day'), now.date().isoformat())[-count:]
            if [r['date'] for r in raw_rows] != [r['date'] for r in rows]:
                raise ValueError('raw_history_dates_mismatch')
            url = SINA_FACTOR_URL.format(code)
            text = market_get(url, host_key='sentiment.sina_factors', parse='text',
                              timeout=6, total_timeout=8, retries=0, min_interval_s=.15)
            if isinstance(text, str) and len(text.encode()) <= 200_000:
                result['raw']['factors'] = {'url': url, 'text': text}
            factors = parse_factors(text, code, now.date().isoformat())
            result['raw']['factors'] = {'url': url, 'text': text, 'records': factors}
            rows, inputs = apply_factors(raw_rows, factors)
            result['raw']['adjustment_inputs'] = inputs
            result['source'] = 'tencent+sina'
            basis = {'status': 'provider_basis', 'method': 'raw_with_sina_qfq_factors',
                     'price_source_url': TENCENT_URL, 'factor_source_url': url,
                     'factor_response_hash': sha256(text.encode()).hexdigest(), 'factor_count': len(factors),
                     'raw_response_hash': fingerprint(result['raw']['unadjusted_request']['response']),
                     'formula': 'adjusted_price = raw_price / dated_qfq_factor', 'inputs': inputs}
        basis.update(range_start=rows[0]['date'], range_end=rows[-1]['date'], row_count=len(rows), observed_at=now.isoformat())
        result.update(rows=rows, status='available', adjustment='qfq', price_basis=basis)
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError) as error:
        result['reason'] = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]+', str(error)) else 'invalid_price_basis'
        result['price_basis']['reason'] = result['reason']
    return result
