import asyncio
from copy import deepcopy

import pytest

from src.modules.short_term.overview_context import collect_report_context, date_ms, changes


def stock(code, level, st=False):
    return {'thscode': code, 'name': code, 'continue_day_cnt': level, 'is_st': st, 'is_new': False}


def fixture(missing_target=False):
    current = [stock('600001.SH', 2), stock('600003.SH', 1)]
    previous = [stock('600001.SH', 1), stock('600002.SH', 1), stock('600004.SH', 1, True)]
    facts = {'trade_date': '2026-11-13', 'previous_trade_date': '2026-11-12', 'intraday': False, 'evidence': [],
             'supplement': {'statistics': {'status': 'available', 'data': {}}, 'pools': {
                 k: {'status': 'available', 'rows': current if k == 'up' else [], 'total': len(current) if k == 'up' else 0}
                 for k in ['up', 'down', 'broken']}}}
    async def fetch(op, args):
        if op.endswith('limit_up_pool'):
            return {'pagination': {'total': len(previous), 'page': 1}, 'item': previous}
        if op.endswith('limit_down_pool'):
            return {'pagination': {'total': 0, 'page': 1}, 'item': []}
        if op.endswith('limit_up_statistics'):
            return {'trade_date': '2026-11-12'}
        if op.endswith('limit_up_ladder'):
            return {'item': []}
        if op.endswith('ths_index_list'):
            return {'item': [{'thscode': '885001.TI', 'name': 'Sector'}]}
        if op.endswith('prices_snapshot'):
            return {'item': [{'thscode': '885001.TI', 'price_change_ratio_pct': 1.0}]}
        if op.endswith('historical_batch'):
            rows = []
            for code in args['thscodes'].split(','):
                bars = [{'date_ms': date_ms('2026-11-12'), 'close_price': 10},
                        {'date_ms': date_ms('2026-11-13'), 'close_price': 8 if code == '600002.SH' else 11},
                        {'date_ms': date_ms('2026-11-16'), 'close_price': 999}]
                if missing_target and code == '600002.SH': bars.pop(1)
                rows.append({'thscode': code, 'item': bars})
            return {'item': rows}
        return {'item': []}
    return facts, fetch


def test_prior_cohort_keeps_failures_excludes_st_and_never_reads_future_bars():
    facts, fetch = fixture()
    context = asyncio.run(collect_report_context(facts, fetch))
    assert context['ready']
    promotion = context['promotions'][0]
    assert (promotion['sample'], promotion['promoted'], promotion['rate']) == (2, 1, .5)
    feedback = context['previous_limit_up_feedback'][0]
    assert feedback['cohort_count'] == 2 and feedback['valid'] == 2
    assert feedback['mean_change_pct'] == pytest.approx(-5)
    assert feedback['positive_count'] == 1
    assert all(row['trade_date'] <= '2026-11-13' for c in context['candidates'] for row in c['history'])


def test_missing_failed_member_blocks_formal_report_instead_of_dropping_the_loss():
    facts, fetch = fixture(missing_target=True)
    context = asyncio.run(collect_report_context(facts, fetch))
    assert not context['ready']
    assert context['previous_limit_up_feedback'][0]['missing'] == 1
    assert '昨日涨停股票的当日收盘行情' in context['missing']


def test_missing_supplement_reports_a_concrete_requirement():
    facts, fetch = fixture()
    facts['supplement']['pools']['broken']['status'] = 'missing'
    context = asyncio.run(collect_report_context(facts, fetch))
    assert not context['ready'] and context['missing']
