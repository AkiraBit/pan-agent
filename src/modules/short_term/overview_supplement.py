"""Optional Fuyao evidence. Never replaces Longbridge breadth or hides failures."""
import asyncio
from collections import Counter
from datetime import datetime, time, timedelta

from marketdata.short_term import TZ
from .facts import evidence, utc_now
from .overview_facts import board, number, timestamp

PREFIX = 'get_a_share_special_data_'


async def supplement(facts, fetch):
    day = facts['trade_date']
    date_ms = int(datetime.combine(datetime.fromisoformat(day).date(), time.min, TZ).timestamp() * 1000)
    audits = []

    async def read(name, args):
        try:
            data = await fetch(PREFIX + name, args)
            if not isinstance(data, dict):
                raise ValueError('invalid_response')
            source_time = timestamp(data.get('timestamp') / 1000) if isinstance(data.get('timestamp'), (int, float)) else None
            received_at = utc_now()
            if not source_time or source_time > received_at + timedelta(seconds=30):
                raise ValueError('missing_or_future_source_time')
            audits.append({'operation': PREFIX + name, 'arguments': args, 'status': 'received',
                           'source_clock_ahead_seconds': max(0, (source_time - received_at).total_seconds())})
            return data
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            audits.append({'operation': PREFIX + name, 'arguments': args, 'status': 'unavailable', 'error_type': type(exc).__name__,
                           'reason': str(exc) if str(exc) in {'missing_or_future_source_time', 'invalid_response'} else 'source_unavailable'})
            return None

    async def pool(kind):
        rows, total, seen = [], None, set()
        for page in range(1, 5):
            data = await read(f'limit_{kind}_pool', {'date_ms': date_ms, 'page': page, 'size': 200})
            if data is None:
                return {'status': 'missing' if not rows else 'partial', 'rows': rows, 'total': total}
            pagination = data.get('pagination', {})
            count = pagination.get('total')
            if type(count) is not int or count < 0 or (total is not None and total != count) or pagination.get('page') != page:
                return {'status': 'partial', 'rows': rows, 'total': total}
            total = count
            batch = data.get('item')
            if not isinstance(batch, list):
                return {'status': 'partial', 'rows': rows, 'total': total}
            for row in batch:
                symbol = row.get('thscode')
                if not symbol or symbol in seen or not board(symbol):
                    return {'status': 'partial', 'rows': rows, 'total': total}
                seen.add(symbol); rows.append(row)
            if len(rows) >= total:
                return {'status': 'available' if len(rows) == total else 'partial', 'rows': rows, 'total': total,
                        'source_time': data.get('timestamp'), 'date_basis': 'explicit_request_date', 'trade_date': day}
        return {'status': 'partial', 'rows': rows, 'total': total}

    # Independent calls; source switches are checked by the injected persisted client.
    up, down, broken, stats, dragon = await asyncio.gather(pool('up'), pool('down'), pool('break'),
        read('limit_up_statistics', {'date': day}), read('dragon_tiger_list', {'date': day, 'board_type': 'all'}))
    stats_ok = bool(stats and stats.get('trade_date') == day and
                    all(type(stats.get(k)) is int and stats[k] >= 0 for k in ['limit_up_stock_count', 'open_stock_count', 'touched_limit_up_stock_count']))
    if stats_ok:
        denominator = stats['touched_limit_up_stock_count']
        rate = number(stats.get('seal_rate'))
        stats_ok = (stats['limit_up_stock_count'] + stats['open_stock_count'] == denominator and
                    (rate is None if denominator == 0 else rate is not None and abs(rate - stats['limit_up_stock_count'] / denominator) < 1e-6))
    ladders = []
    for name in ('main', 'growth', 'star', 'beijing'):
        members = [r for r in up['rows'] if board(r['thscode']) == name]
        eligible = [r for r in members if r.get('is_st') is False and r.get('is_new') is False]
        valid = [r for r in eligible if type(r.get('continue_day_cnt')) is int and r['continue_day_cnt'] >= 1]
        counts = Counter(r['continue_day_cnt'] for r in valid)
        ladders.append({'board': name, 'status': 'available' if up['status'] == 'available' and len(valid) == len(eligible) else 'partial',
                        'sample': len(valid), 'excluded_or_unknown': len(members) - len(eligible),
                        'levels': [{'level': n, 'count': counts[n]} for n in sorted(counts)],
                        'highest': max(counts) if counts else None,
                        'first_board_ratio': counts[1] / len(valid) if valid else None})
    dragon_ok = bool(dragon and dragon.get('trade_date') == day and isinstance(dragon.get('stock_items'), list))
    result = {'provider': 'fuyao_rest', 'trade_date': day, 'collected_at': utc_now().isoformat(),
              'statistics': {'status': 'available' if stats_ok else 'missing' if not stats else 'conflicted', 'data': stats},
              'pools': {'up': up, 'down': down, 'broken': broken}, 'ladders': ladders,
              'dragon_tiger': {'status': 'available' if dragon_ok else 'missing' if not dragon else 'conflicted',
                              'data': dragon, 'publication_time': None, 'scope': 'disclosed_records_not_whole_market_flow'},
              'notes': ['pool_dates_bound_by_request_not_original_publication_archive',
                        'vendor_statistics_and_filtered_ladder_have_separate_denominators',
                        'page_board_promotion_is_not_frozen_cohort_promotion',
                        'dragon_tiger_multi_day_records_must_not_be_summed_with_one_day_records'], 'audit': audits}
    facts['supplement'] = result
    facts['collected_at'] = result['collected_at']
    for key, title in [('statistics', 'Fuyao limit-up statistics'), ('ladders', 'Fuyao board-separated streak ladder'),
                       ('pools', 'Fuyao limit event pools'), ('dragon_tiger', 'Fuyao disclosed dragon-tiger records')]:
        facts['evidence'].append(evidence('overview:fuyao-' + key, 'market_structure', title, 'Fuyao REST', result[key],
                                          result['collected_at']))
    return facts
