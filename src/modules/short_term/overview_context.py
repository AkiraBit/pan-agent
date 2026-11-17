"""Recent tape, sector leadership and named candidates for the decision page."""
import asyncio
from datetime import datetime, time, timedelta

from marketdata.short_term import TZ
from .facts import evidence, utc_now
from .overview_facts import board, number, quote_row

SPECIAL = 'get_a_share_special_data_'
INDEX = 'get_a_share_index_'
INDEX_NAMES = {'000001.SH': '上证指数', '399001.SZ': '深证成指', '399006.SZ': '创业板指',
               '000688.SH': '科创50', '000852.SH': '中证1000'}


def date_ms(day):
    return int(datetime.combine(datetime.fromisoformat(day).date(), time.min, TZ).timestamp() * 1000)


def dated_bars(series, day):
    result = []
    for row in series.get('item', []):
        stamp = number(row.get('date_ms'))
        close = number(row.get('close_price'))
        if stamp is None or close is None or close <= 0:
            continue
        date = datetime.fromtimestamp(stamp / 1000, TZ).date().isoformat()
        if date <= day:
            result.append({**row, 'trade_date': date})
    return sorted(result, key=lambda r: r['trade_date'])


def changes(series, day):
    bars = dated_bars(series, day)
    result = []
    for before, current in zip(bars, bars[1:]):
        result.append({'trade_date': current['trade_date'], 'close': current['close_price'],
                       'change_pct': (current['close_price'] / before['close_price'] - 1) * 100,
                       'turnover': current.get('turnover'), 'open': current.get('open_price'),
                       'high': current.get('high_price'), 'low': current.get('low_price')})
    return result


def eligible(rows):
    return [r for r in rows if r.get('is_st') is False and r.get('is_new') is False and board(r['thscode'])]


async def collect_report_context(facts, fetch):
    """Use existing authorized APIs; retain provenance behind the presentation layer."""
    day, prior = facts['trade_date'], facts.get('previous_trade_date')
    supplement = facts.get('supplement', {})
    missing, calls = [], []
    semaphore = asyncio.Semaphore(4)

    async def read(op, args):
        try:
            async with semaphore:
                result = await asyncio.wait_for(fetch(op, args), 30)
            if not isinstance(result, dict):
                raise ValueError('invalid_response')
            calls.append({'operation': op, 'arguments': args, 'source': '扶摇', 'status': 'received'})
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            calls.append({'operation': op, 'arguments': args, 'source': '扶摇', 'status': 'unavailable'})
            return {}

    async def pool(kind, date):
        rows = []
        for page in range(1, 5):
            data = await read(SPECIAL + f'limit_{kind}_pool', {'date_ms': date_ms(date), 'page': page, 'size': 200})
            pagination = data.get('pagination', {})
            if not isinstance(data.get('item'), list) or type(pagination.get('total')) is not int:
                return None
            rows.extend(data['item'])
            if len(rows) == pagination['total'] and len({r['thscode'] for r in rows}) == len(rows):
                return rows
            if len(rows) >= pagination['total']:
                return None
        return None

    if not prior or supplement.get('statistics', {}).get('status') != 'available' or any(supplement.get('pools', {}).get(k, {}).get('status') != 'available' for k in ('up', 'down', 'broken')):
        return {'ready': False, 'missing': ['当日完整涨停、跌停、炸板池及前一交易日'], 'calls': calls}

    previous_up, previous_down, previous_stats, ladder, concepts, industries = await asyncio.gather(
        pool('up', prior), pool('down', prior), read(SPECIAL + 'limit_up_statistics', {'date': prior}),
        read(SPECIAL + 'limit_up_ladder', {}), read(INDEX + 'catalog_ths_index_list', {'tag': 'cn_concept'}),
        read(INDEX + 'catalog_ths_index_list', {'tag': 'industry'}))
    current_up = eligible(supplement['pools']['up']['rows'])
    previous_up_filtered = eligible(previous_up or [])
    if previous_up is None or previous_down is None or previous_stats.get('trade_date') != prior:
        missing.append('上一交易日涨跌停池与晋级统计')

    start = date_ms((datetime.fromisoformat(day) - timedelta(days=14)).date().isoformat())
    end = date_ms(day) + 86399000

    async def history(codes, stock=False):
        result = []
        op = 'get_a_share_prices_historical_batch' if stock else INDEX + 'prices_historical_batch'
        for offset in range(0, len(codes), 10):
            args = {'thscodes': ','.join(codes[offset:offset + 10]), 'interval': '1d', 'start': start, 'end': end}
            if stock:
                args['adjust'] = 'forward'
            data = await read(op, args)
            result.extend(data.get('item', []))
        return result

    async def sectors(catalog, kind):
        names = {r['thscode']: r['name'] for r in catalog.get('item', [])}
        if not names:
            missing.append('概念/行业指数目录')
            return []
        quotes = await read(INDEX + 'prices_snapshot', {'thscodes': ','.join(names)})
        rows = [r for r in quotes.get('item', []) if number(r.get('price_change_ratio_pct')) is not None]
        if len(rows) != len(names):
            missing.append('概念/行业完整行情排名')
        rows.sort(key=lambda r: r['price_change_ratio_pct'], reverse=True)
        selected = rows[:10]
        series = {r['thscode']: changes(r, day) for r in await history([r['thscode'] for r in selected])}
        if any(not series.get(r['thscode']) or series[r['thscode']][-1]['trade_date'] != day for r in selected):
            missing.append('重点概念/行业当日及前日指数日线')
        return [{'symbol': r['thscode'], 'name': names.get(r['thscode'], r['thscode']), 'kind': kind,
                 'rank': i + 1, 'rank_universe': len(rows), 'change_pct': r['price_change_ratio_pct'],
                 'turnover': r.get('turnover'), 'history': series.get(r['thscode'], []), 'source': '扶摇 · 同花顺指数'}
                for i, r in enumerate(selected)]

    stock_codes = sorted({r['thscode'] for r in current_up + previous_up_filtered})
    concept_leaders, industry_leaders, index_history, stock_history = await asyncio.gather(
        sectors(concepts, 'concept'), sectors(industries, 'industry'), history(list(INDEX_NAMES)), history(stock_codes, True))
    stock_series = {r['thscode']: changes(r, day) for r in stock_history}
    quotes = {r['symbol']: r for r in facts.get('raw', {}).get('quotes', [])}
    stock_today = {}
    for code in stock_codes:
        series = stock_series.get(code, [])
        current = next((r for r in reversed(series) if r['trade_date'] == day), None)
        # Prefer the official previous-close reference from the Longbridge quote;
        # adjusted daily bars cover an otherwise missing prior-day cohort member.
        q = quotes.get(code, {})
        valid_quote = quote_row(q, code, day, utc_now()) if q else None
        if valid_quote:
            current = {'trade_date': day, 'close': valid_quote['price'],
                       'change_pct': valid_quote['change_pct'], 'source': '长桥 MCP'}
        if current:
            stock_today[code] = {**current, 'source': current.get('source', '扶摇 · 个股日线')}
    feedback = []
    for scope in ('main', 'growth', 'star', 'beijing'):
        cohort = [r for r in previous_up_filtered if board(r['thscode']) == scope]
        values = [stock_today[r['thscode']]['change_pct'] for r in cohort if r['thscode'] in stock_today]
        feedback.append({'board': scope, 'cohort_count': len(cohort), 'valid': len(values),
                         'mean_change_pct': sum(values) / len(values) if values else None,
                         'positive_count': sum(v > 0 for v in values), 'missing': len(cohort) - len(values),
                         'sources': sorted({stock_today[r['thscode']]['source'] for r in cohort if r['thscode'] in stock_today})})
    if any(r['missing'] for r in feedback):
        missing.append('昨日涨停股票的当日收盘行情')
    today_by_code = {r['thscode']: r for r in current_up}
    promotions = []
    for scope in ('main', 'growth', 'star', 'beijing'):
        for level in sorted({r['continue_day_cnt'] for r in previous_up_filtered if board(r['thscode']) == scope}):
            cohort = [r for r in previous_up_filtered if board(r['thscode']) == scope and r['continue_day_cnt'] == level]
            promoted = [r['thscode'] for r in cohort if today_by_code.get(r['thscode'], {}).get('continue_day_cnt') == level + 1]
            promotions.append({'board': scope, 'from_level': level, 'sample': len(cohort), 'promoted': len(promoted),
                               'rate': len(promoted) / len(cohort), 'members': [r['thscode'] for r in cohort]})
    indices = [{'symbol': r['thscode'], 'name': INDEX_NAMES[r['thscode']], 'history': changes(r, day),
                'source': '扶摇 · 指数日线'} for r in index_history if r['thscode'] in INDEX_NAMES]
    if len(indices) != len(INDEX_NAMES) or any(not r['history'] or r['history'][-1]['trade_date'] != day for r in indices):
        missing.append('主要指数当日及前日行情')
    # Compare turnover only within the same index series; never sum overlapping indices.
    members = await read(INDEX + 'constituents_ths_index_list_by_stock', {'thscode': ','.join(r['thscode'] for r in current_up), 'type': 'cn_concept'}) if current_up else {}
    memberships = {r['thscode']: r.get('index_list', []) for r in members.get('item', [])}
    candidates = [{**r, 'board': board(r['thscode']), 'history': stock_series.get(r['thscode'], []),
                   'concepts': memberships.get(r['thscode'], []), 'source': '扶摇 · 涨停池/个股日线/当前概念'} for r in current_up]
    result = {'ready': not missing, 'trade_date': day, 'previous_trade_date': prior, 'missing': sorted(set(missing)),
              'session_comparison': {'previous_statistics': previous_stats, 'current_statistics': supplement['statistics'].get('data'),
                 'previous_down_count': len(previous_down) if previous_down is not None else None,
                 'current_down_count': supplement['pools']['down']['total'], 'pool_scope': 'supplier_pool_all_records'},
              'promotions': promotions, 'previous_limit_up_feedback': feedback,
              'indices': indices, 'concept_leaders': concept_leaders, 'industry_leaders': industry_leaders,
              'ladder_history': [r for r in ladder.get('item', []) if r.get('date', '') <= day][:10],
              'candidates': candidates, 'calls': calls}
    for key, title in [('session_comparison', '跨日涨跌停与封板变化'), ('promotions', '前日涨停队列晋级'),
                       ('previous_limit_up_feedback', '昨日涨停股今日反馈'), ('indices', '主要指数近期表现'),
                       ('concept_leaders', '概念领涨与近期表现'), ('industry_leaders', '行业领涨与近期表现'),
                       ('ladder_history', '近期连板高度与梯队'), ('candidates', '候选股事实与当前题材')]:
        source = ('扶摇昨日涨停池 + ' + ' / '.join(sorted({s for r in feedback for s in r['sources']}))) if key == 'previous_limit_up_feedback' else '扶摇 REST'
        facts['evidence'].append(evidence('overview:context-' + key, 'report_context', title, source, result[key], utc_now()))
    facts['report_context'] = result
    facts['collected_at'] = utc_now().isoformat()
    return result
