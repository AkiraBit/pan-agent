"""Independent A-share universe and dated Tencent snapshots for sentiment reads.

Sina supplies the paginated universe, not an inferred quote date. Tencent supplies
each quote's own timestamp. No fetch timestamp is substituted for source time.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime

from marketdata.http import market_get
from marketdata.short_term import Batch, TZ, number

SINA = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'}
_cache = {}
_lock = threading.Lock()


def read_json(url, params):
    return market_get(url, host_key='sentiment.universe', params=params, headers=HEADERS,
                      parse='json', timeout=6, total_timeout=8, retries=0, min_interval_s=.08)


def universe():
    count = read_json(SINA + 'getHQNodeStockCount', {'node': 'hs_a'})
    try:
        count = int(count)
    except (ValueError, TypeError):
        return [], False
    if not 1000 <= count <= 9000:
        return [], False

    def page(n):
        return read_json(SINA + 'getHQNodeData', {'page': n, 'num': 80, 'sort': 'symbol', 'asc': 1, 'node': 'hs_a'})

    with ThreadPoolExecutor(max_workers=6) as pool:
        pages = list(pool.map(page, range(1, math.ceil(count / 80) + 1)))
    rows = [r for p in pages if isinstance(p, list) for r in p if isinstance(r, dict)]
    unique = {r.get('symbol'): r for r in rows}
    complete = len(rows) == len(unique) == count and all(isinstance(p, list) for p in pages)
    symbols = sorted(s for s in unique if isinstance(s, str) and re.fullmatch(r'(?:sh6|sz[03])\d{5}', s))
    return symbols, complete


def parse_quote(line):
    match = re.match(r'v_((?:sh|sz)\d{6})="(.*)";?', line.strip())
    if not match:
        return None
    code, raw = match.groups()
    p = raw.split('~')
    if len(p) < 50 or p[2] != code[2:]:
        return None
    try:
        stamp = datetime.strptime(p[30], '%Y%m%d%H%M%S').replace(tzinfo=TZ)
    except ValueError:
        return None
    price, previous = number(p[3]), number(p[4])
    return {'symbol': p[2] + ('.SH' if code.startswith('sh') else '.SZ'), 'code': p[2], 'name': p[1],
            'price': price, 'prev_close': previous, 'open': number(p[5]), 'high': number(p[33]), 'low': number(p[34]),
            'change_pct': number(p[32]), 'change': number(p[32]),
            'volume_shares': (number(p[6]) * 100 if number(p[6]) is not None else None),
            'amount_cny': (number(p[37]) * 10000 if number(p[37]) is not None else None),
            'turnover_rate': number(p[38]), 'source_time': stamp.isoformat(), 'trade_date': stamp.date().isoformat(),
            'source': 'tencent', 'bid_price': number(p[9]), 'ask_price': number(p[19]),
            # These are order-book quotes. They are NOT auction matched/unmatched quantities.
            'bid_volume_shares': (number(p[10]) or 0) * 100, 'ask_volume_shares': (number(p[20]) or 0) * 100}


def snapshots(symbols):
    codes = [s if re.fullmatch(r'(?:sh|sz)\d{6}', s) else s[-2:].lower() + s[:6] for s in symbols]
    codes = list(dict.fromkeys(c for c in codes if re.fullmatch(r'(?:sh|sz)\d{6}', c)))

    def group(items):
        raw = market_get('https://qt.gtimg.cn/q=' + ','.join(items), host_key='sentiment.tencent',
                         parse='text', encoding='gbk', timeout=6, total_timeout=12, retries=1, min_interval_s=.12)
        return [q for line in (raw or '').splitlines() if (q := parse_quote(line))]

    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(pool.map(group, [codes[i:i+150] for i in range(0, len(codes), 150)]))
    wanted = set(codes)
    return list({q['symbol']: q for rows in groups for q in rows
                 if q['symbol'][-2:].lower() + q['symbol'][:6] in wanted}.values())


def market_snapshot():
    with _lock:
        saved = _cache.get('market')
        if saved and time.monotonic() - saved[0] < 90:
            return deepcopy(saved[1])
        symbols, complete = universe()
        batch = Batch('market', provider='sina_universe+tencent', expected=len(symbols) if complete else None)
        if not symbols:
            return batch
        data = snapshots(symbols)
        batch.rows = [{'code': q['code'], 'name': q['name'], 'price': q['price'], 'change': q['change'],
                       'amount': q['amount_cny'], 'volume': (q['volume_shares'] or 0) / 100,
                       'source_time': datetime.fromisoformat(q['source_time']).timestamp()} for q in data]
        batch.status = 'complete' if complete and len(data) == len(symbols) else 'partial'
        batch.reason = 'ok' if batch.status == 'complete' else 'incomplete_universe_or_quotes'
        batch.received_at = datetime.now(TZ).isoformat()
        days = {q['trade_date'] for q in data}
        batch.trade_date = next(iter(days)) if len(days) == 1 else None
        if data:
            _cache['market'] = (time.monotonic(), deepcopy(batch))
        return batch


def daily_series(symbol, count=80):
    """A consistently adjusted series, retaining raw responses and factor proof."""
    from marketdata.price_adjustment import adjusted_daily_series
    return adjusted_daily_series(symbol, count)
