"""Longbridge-only market overview, with source dates and explicit proxy metrics."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import datetime, timedelta, time
from statistics import median

from marketdata.short_term import TZ

from .facts import evidence, utc_now

INDEX_SYMBOLS = ['000001.SH', '399001.SZ', '399006.SZ', '000688.SH']
THRESHOLDS = {'main': 5., 'growth': 10., 'star': 10., 'beijing': 15.}
REQUEST_INTERVAL = .55  # Upstream screener has a per-second quota shared by sessions.


class RateLimited(ValueError):
    pass


def unpack(result):
    if result.get('isError'):
        for part in result.get('content', []):
            try:
                error = json.loads(part.get('text', ''))
                if isinstance(error, dict) and error.get('error_code') == 429002:
                    raise RateLimited('longbridge_rate_limited')
            except json.JSONDecodeError:
                pass
        raise ValueError('longbridge_query_failed')
    value = result.get('structuredContent')
    if value is not None:
        if isinstance(value, dict) and value.get('_truncated'):
            raise ValueError('longbridge_truncated_response')
        return value
    if any(p.get('type') == 'text' and p.get('text', '').startswith('[TRUNCATED') for p in result.get('content', [])):
        raise ValueError('longbridge_truncated_response')
    for part in result.get('content', []):
        if part.get('type') == 'text':
            try:
                value = json.loads(part['text'])
            except (ValueError, KeyError):
                continue
            if isinstance(value, dict) and value.get('_truncated'):
                raise ValueError('longbridge_truncated_response')
            return value
    raise ValueError('longbridge_invalid_response')


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, TZ)
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(TZ) if result.tzinfo else result.replace(tzinfo=TZ)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def board(symbol):
    if symbol.endswith('.BJ'):
        return 'beijing'
    if symbol.startswith(('300', '301')) and symbol.endswith('.SZ'):
        return 'growth'
    if symbol.startswith(('688', '689')) and symbol.endswith('.SH'):
        return 'star'
    if symbol.startswith(('000', '001', '002', '003', '600', '601', '603', '605')) and symbol.endswith(('.SH', '.SZ')):
        return 'main'
    return None


def quantile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def breadth(rows):
    values = [r['change_pct'] for r in rows]
    return {'valid': len(values), 'rising': sum(v > 0 for v in values),
            'falling': sum(v < 0 for v in values), 'flat': sum(v == 0 for v in values),
            'positive_ratio': sum(v > 0 for v in values) / len(values) if values else None,
            'median': median(values) if values else None, 'p10': quantile(values, .1), 'p90': quantile(values, .9)}


def quote_row(raw, name, day, observed):
    stamp = timestamp(raw.get('timestamp'))
    price, previous = number(raw.get('last_done')), number(raw.get('prev_close'))
    if (not stamp or stamp.date().isoformat() != day or stamp > observed + timedelta(seconds=30)
            or price is None or price <= 0 or previous is None or previous <= 0
            or raw.get('trade_status') != 'Normal'):
        return None
    return {'symbol': raw['symbol'], 'name': name, 'price': price, 'change_pct': (price / previous - 1) * 100,
            'amount_cny': number(raw.get('turnover')), 'source_time': stamp.isoformat(), 'board': board(raw['symbol'])}


async def collect_overview(query, previous=None, *, now=None):
    """query calls the configured MCP with credentials kept outside the fact object."""
    started = now or utc_now()
    local = started.astimezone(TZ)
    calls, failures, raw = [], [], {}
    semaphore = asyncio.Semaphore(4)
    pacing = asyncio.Lock()
    next_request = 0.

    async def request(tool, arguments):
        nonlocal next_request
        for attempt in range(3):
            async with pacing:
                loop = asyncio.get_running_loop()
                await asyncio.sleep(max(0, next_request - loop.time()))
                next_request = loop.time() + REQUEST_INTERVAL
            try:
                return unpack(await query(tool, arguments))
            except RateLimited:
                calls.append({'tool': tool, 'arguments': arguments, 'status': 'rate_limited', 'attempt': attempt + 1})
                if attempt == 2:
                    raise
                await asyncio.sleep(REQUEST_INTERVAL * (2 ** (attempt + 1)))

    async def read(tool, arguments, *, optional=False):
        async with semaphore:
            try:
                data = await request(tool, arguments)
                digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                calls.append({'tool': tool, 'arguments': arguments, 'status': 'ok', 'content_hash': digest})
                return data
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                calls.append({'tool': tool, 'arguments': arguments, 'status': 'failed'})
                if optional:
                    failures.append(tool)
                    return None
                detail = getattr(exc, 'detail', {})
                raise ValueError(detail.get('code', 'longbridge_query_failed') if isinstance(detail, dict) else 'longbridge_query_failed') from exc

    calendar = await read('trading_days', {'market': 'CN', 'start': (local.date() - timedelta(days=40)).isoformat(),
                                           'end': (local.date() + timedelta(days=20)).isoformat()})
    days = sorted(set(calendar.get('trade_days', [])))
    eligible_days = [d for d in days if d < local.date().isoformat() or (d == local.date().isoformat() and local.time() >= time(9, 30))]
    if not eligible_days:
        raise ValueError('calendar_unknown')
    day = eligible_days[-1]
    previous_day = eligible_days[-2] if len(eligible_days) >= 2 else None
    intraday = day == local.date().isoformat() and local.time() < time(15)
    first_args = {'market': 'CN', 'conditions': [], 'extra_returns': ['marketcap'],
                  '_jq': '{total,items:[.items[]|{symbol,name}]}',
                  'sort_by_key': 'marketcap', 'sort_order': 'desc', 'size': 100, 'page': 0}
    first = await read('screener_search', first_args)
    total = first.get('total')
    if not isinstance(total, int) or total <= 0:
        raise ValueError('market_data_unavailable')
    pages = [first]
    page_count = min(math.ceil(total / 100), 80)
    # Small batches bound concurrent sessions and preserve diagnostic page failures.
    for start in range(1, page_count, 4):
        pages.extend(await asyncio.gather(*(read('screener_search', {**first_args, 'page': page}, optional=True)
                                           for page in range(start, min(start + 4, page_count)))))
    directory = {}
    duplicates, returned = 0, 0
    for page in pages:
        for row in (page or {}).get('items', []):
            returned += 1
            symbol = row.get('symbol', '')
            duplicates += int(symbol in directory)
            if board(symbol):
                directory[symbol] = row.get('name', symbol)
    if not directory:
        raise ValueError('market_data_unavailable')
    symbols = list(directory)
    quote_filter = '.[]|{symbol,last_done,prev_close,turnover,trade_status,timestamp}'
    batches = await asyncio.gather(*(read('quote', {'symbols': symbols[i:i + 100], '_jq': quote_filter}, optional=True)
                                     for i in range(0, len(symbols), 100)))
    batches = [([b] if isinstance(b, dict) and 'symbol' in b else b) for b in batches]
    raw_quotes = [r for batch in batches if isinstance(batch, list) for r in batch if isinstance(r, dict)]
    index_data, temperature, temperature_history = await asyncio.gather(
        read('quote', {'symbols': INDEX_SYMBOLS, '_jq': quote_filter}, optional=True),
        read('market_temperature', {'market': 'CN'}, optional=True),
        read('history_market_temperature', {'market': 'CN', 'start': (local.date() - timedelta(days=40)).isoformat(), 'end': day}, optional=True))
    observed = now or utc_now()
    rows_by_symbol = {}
    excluded_st = 0
    excluded_halted = 0
    stale = 0
    for q in raw_quotes:
        symbol = q.get('symbol')
        if symbol not in directory:
            continue
        if 'ST' in directory[symbol].upper() or '退' in directory[symbol]:
            excluded_st += 1
            continue
        if q.get('trade_status') == 'Halted':
            excluded_halted += 1
            continue
        row = quote_row(q, directory[symbol], day, observed)
        if row:
            rows_by_symbol[symbol] = row
        else:
            stale += 1
    rows = list(rows_by_symbol.values())
    if not rows:
        raise ValueError('market_data_stale')
    complete = (all(p is not None and p.get('total') == total for p in pages) and returned == total
                and not duplicates and len(raw_quotes) == len(symbols) and not stale
                and len(rows) + excluded_st + excluded_halted == len(symbols)
                and all(isinstance(b, list) for b in batches))
    coverage = {'status': 'complete' if complete else 'partial', 'directory_total': total,
                'directory_count': len(directory), 'valid': len(rows), 'excluded_st': excluded_st, 'excluded_halted': excluded_halted,
                'missing_or_stale': len(symbols) - excluded_st - excluded_halted - len(rows),
                'directory_missing': max(0, total - returned), 'duplicate_directory_rows': duplicates,
                'excluded_unsupported': returned - duplicates - len(directory),
                'scope': 'longbridge_cn_directory_ex_st', 'started_at': started.isoformat(), 'finished_at': observed.isoformat()}
    boards = []
    for name, threshold in THRESHOLDS.items():
        group = [r for r in rows if r['board'] == name]
        group_total = sum(board(s) == name for s in directory)
        boards.append({'board': name, 'directory_count': group_total, **breadth(group),
                       'strong_count': sum(r['change_pct'] >= threshold for r in group) if group else None,
                       'weak_count': sum(r['change_pct'] <= -threshold for r in group) if group else None,
                       'threshold_pct': threshold, 'threshold_status': 'uncalibrated_proxy'})
    metrics = {'breadth': breadth(rows), 'boards': boards, 'limit_up': None, 'limit_down': None,
               'break_rate': None, 'promotion_rate': None}
    # Daily comparison requires the immediately preceding session and completed snapshots.
    history = [h for h in (previous or {}).get('daily_observations', []) if h['trade_date'] < day]
    prior = next((h for h in reversed(history) if h['trade_date'] == previous_day), None)
    universe_hash = hashlib.sha256('\n'.join(sorted(rows_by_symbol)).encode()).hexdigest()
    comparable = bool(prior and not intraday and prior.get('coverage_status') == coverage['status'] == 'complete'
                      and prior.get('universe_hash') == universe_hash)
    metrics['comparison'] = {'status': 'available' if comparable else 'unavailable',
        'previous_trade_date': previous_day,
        'previous': prior['metrics'] if comparable else None,
        'reason': None if comparable else 'no_comparable_completed_snapshot'}
    frozen = prior.get('strong_cohort', []) if prior else []
    cohort = [rows_by_symbol[s] for s in frozen if s in rows_by_symbol]
    feedback = {'status': 'missing' if not frozen else 'proxy', 'reason': 'no_prior_snapshot' if not prior else 'empty_cohort' if not frozen else None,
                'basis': 'previous_completed_session_strong_proxy_cohort',
                'cohort_trade_date': previous_day, 'cohort_count': len(frozen), 'valid': len(cohort),
                'mean_change_pct': sum(r['change_pct'] for r in cohort) / len(cohort) if cohort else None,
                'positive_ratio': sum(r['change_pct'] > 0 for r in cohort) / len(cohort) if cohort else None,
                'missing': len(frozen) - len(cohort), 'intraday': intraday}
    metrics['feedback'] = feedback
    indices = [r for q in (index_data or []) if (r := quote_row(q, q.get('symbol', ''), day, observed))] if isinstance(index_data, list) else []
    temp_stamp = timestamp((temperature or {}).get('timestamp'))
    temp_valid = bool(temp_stamp and temp_stamp.date().isoformat() == day and temp_stamp <= observed)
    temperature = {**(temperature or {}), 'quality': 'available' if temp_valid else 'stale' if temperature else 'unavailable'}
    ev = [evidence('overview:coverage', 'coverage', 'Longbridge coverage', 'Longbridge MCP', coverage, observed),
          evidence('overview:breadth', 'breadth', 'Market breadth and return distribution', 'Longbridge MCP · quote', metrics['breadth'], observed),
          evidence('overview:boards', 'boards', 'Board breadth and strong/weak proxies', 'Longbridge MCP · quote', boards, observed),
          evidence('overview:feedback', 'cohort', 'Frozen strong-cohort feedback', 'PanWatch + Longbridge MCP', feedback, observed, status=feedback['status']),
          evidence('overview:comparison', 'comparison', 'Comparable previous-session observation', 'PanWatch', metrics['comparison'], observed),
          evidence('overview:indices', 'indices', 'Index background', 'Longbridge MCP · quote', indices, observed),
          evidence('overview:temperature', 'temperature', 'Vendor market temperature (context only)', 'Longbridge MCP', temperature, observed, status=temperature['quality']),
          evidence('overview:gaps', 'data_quality', 'Unavailable metrics and proxy boundaries', 'PanWatch',
                   {'missing': ['official_limit_prices', 'limit_event_pools', 'promotion', 'MA20_breadth', '20_60_day_high_low'],
                    'failed_tools': sorted(set(failures)), 'proxy_thresholds': THRESHOLDS, 'calibration': 'not_backtested',
                    'no_timestamp_screener_used_only_as_directory': True, 'atomic_snapshot': False}, observed)]
    if temperature_history:
        ev.append(evidence('overview:temperature-history', 'temperature_history', 'Vendor temperature history', 'Longbridge MCP', temperature_history, observed))
    if not intraday:
        history.append({'trade_date': day, 'coverage_status': coverage['status'], 'universe_hash': universe_hash,
                        'metrics': {'breadth': metrics['breadth']},
                        'strong_cohort': [r['symbol'] for r in rows if r['change_pct'] >= THRESHOLDS[r['board']]]})
    future_days = [d for d in days if d > day]
    if not complete or intraday or (local.date().isoformat() == day and local.time() < time(16, 30)):
        refresh_after = observed + timedelta(minutes=10)
    else:
        refresh_after = datetime.combine(datetime.fromisoformat(future_days[0]).date(), time(9, 31), TZ) if future_days else observed + timedelta(hours=6)
    raw.update(calendar=calendar, directory_pages=pages, quotes=raw_quotes, indices=index_data, calls=calls)
    return {'trade_date': day, 'previous_trade_date': previous_day, 'as_of': max(r['source_time'] for r in rows),
            'collected_at': observed.isoformat(), 'refresh_after': refresh_after.isoformat(), 'intraday': intraday,
            'provider': 'longbridge_mcp', 'coverage': coverage, 'metrics': metrics, 'indices': indices,
            'temperature': temperature, 'evidence': ev, 'daily_observations': history[-10:], 'raw': raw}
