"""Auditable 2026 price-deviation reference windows, never an exchange verdict."""
from __future__ import annotations

from datetime import date, timedelta

from src.platform.scheduling.trading_calendar import calendar_known, is_trading_day

SSE_RULE = 'https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml'
SZSE_RULE = 'https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf'
EFFECTIVE = '2026-07-06'


def profile(symbol):
    code = symbol[:6]
    star = code.startswith(('688', '689')) and symbol.endswith('.SH')
    growth = code.startswith(('300', '301')) and symbol.endswith('.SZ')
    return {'rule_version': '2026-07-06', 'effective_from': EFFECTIVE,
            'source_url': SSE_RULE if symbol.endswith('.SH') else SZSE_RULE,
            'board': 'star' if star else 'growth' if growth else 'main',
            'benchmark': 'sh000688' if star else 'sz399102' if growth else 'sh000002' if symbol.endswith('.SH') else 'sz399107',
            'ordinary_threshold': 30 if star or growth else 20,
            'repeat_count_threshold': 3 if star or growth else 4,
            'method': '100 * (adjusted_stock_end / adjusted_stock_base - benchmark_end / benchmark_base)'}


def reference_windows(symbol, stock, benchmark, as_of):
    rule = profile(symbol)
    output = {'symbol': symbol, **rule, 'as_of': as_of, 'status': 'unavailable', 'windows': [],
              'official_determination': 'unknown', 'reset_status': 'unverified',
              'missing': ['official_reset_and_resumption_history', 'no_limit_session_history',
                          'turnover_abnormality', 'exchange_confirmed_repeat_events'],
              'basis': 'rolling_reference_not_active_regulatory_window'}
    if as_of < EFFECTIVE:
        output['reason'] = 'rule_version_not_supported'
        return output
    output['price_basis'] = stock.get('price_basis', {})
    if stock.get('adjustment') != 'qfq':
        output['reason'] = 'corporate_action_adjustment_unverified'
        return output
    sr = {r['date']: r for r in stock.get('rows', []) if r['date'] <= as_of}
    br = {r['date']: r for r in benchmark.get('rows', []) if r['date'] <= as_of}
    if len(sr) < 2 or as_of not in sr or as_of not in br:
        output['reason'] = 'history_incomplete'
        return output
    output['adjustment'] = stock.get('adjustment')
    for size, up, down in [(3, rule['ordinary_threshold'], -rule['ordinary_threshold']), (10, 100, -50), (30, 200, -70)]:
        dates, cursor = [], date.fromisoformat(as_of)
        for _ in range(70):
            if not calendar_known('CN', cursor):
                break
            if is_trading_day('CN', cursor):
                dates.append(cursor.isoformat())
                if len(dates) == size + 1:
                    break
            cursor -= timedelta(days=1)
        dates.reverse()
        row = {'sessions': size, 'upper': up, 'lower': down, 'status': 'unavailable', 'basis': 'rolling_reference'}
        if len(dates) != size+1 or dates[1] < EFFECTIVE or any(d not in sr or d not in br for d in dates):
            row['reason'] = 'missing_trading_day_or_rule_transition'
        elif any(sr[d]['close'] <= 0 or br[d]['close'] <= 0 for d in dates):
            row['reason'] = 'invalid_price'
        else:
            base, end = dates[0], dates[-1]
            stock_return = (sr[end]['close'] / sr[base]['close'] - 1) * 100
            index_return = (br[end]['close'] / br[base]['close'] - 1) * 100
            deviation = stock_return-index_return
            row.update(status='calculated', start=dates[1], end=end, base_date=base,
                       stock_return=round(stock_return, 6), benchmark_return=round(index_return, 6),
                       deviation=round(deviation, 6), upper_distance=round(up-deviation, 6),
                       lower_distance=round(deviation-down, 6), threshold_crossed=deviation >= up or deviation <= down,
                       inputs=[{'date': d, 'stock_close': sr[d]['close'], 'benchmark_close': br[d]['close']} for d in dates])
        output['windows'].append(row)
    output['status'] = 'reference_only' if any(w['status']=='calculated' for w in output['windows']) else 'unavailable'
    return output
