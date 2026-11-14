from datetime import datetime, timedelta

import pytest
from marketdata.short_term import Batch, POOLS, TZ, pool_clock
from src.modules.short_term.api import completed_day
from src.modules.short_term.speculation import (
    candidate_concepts, positive_integer, relay_observation, theme_observation,
    trend_candidates, trend_structure,
)


def stock(code, level=1, change=10):
    return {'code': code, 'name': code, 'change': change, 'streak': level,
            'previous_streak': level, 'amount': 100, 'first_time': '09:30:00'}


def batch(rows):
    return Batch('test', rows, len(rows), 'complete', 'ok')


def pools():
    return {k: batch([]) for k in POOLS}


def test_relay_keeps_correct_cohort_denominator():
    p = pools()
    p['yesterday'] = batch([stock('A', 1), stock('B', 1, -3), stock('C', 3, -10)])
    p['up'] = batch([stock('A', 2), stock('D', 1)])
    p['down'] = batch([stock('C')])
    r = relay_observation(p)
    assert r['promotion'] == [{'level': 1, 'total': 2, 'promoted': 1, 'rate': .5},
                              {'level': 3, 'total': 1, 'promoted': 0, 'rate': 0}]
    assert r['height'] == 2 and r['previous_height'] == 3
    assert r['anchors'][0]['state'] == 'limit_down'
    assert r['negative_feedback'][0]['code'] == 'C'
    assert r['negative_feedback'][1]['state'] == 'not_sealed'


@pytest.mark.parametrize('fault', ['partial', 'conflict', 'overlap', 'missing_change'])
def test_unknown_feedback_does_not_become_failed_promotion(fault):
    p = pools()
    p['yesterday'] = batch([stock('A', 1)])
    if fault == 'partial':
        p['up'].status = 'partial'
    elif fault == 'overlap':
        p['up'] = batch([stock('A', 2)])
        p['broken'] = batch([stock('A')])
    elif fault == 'conflict':
        p['up'] = batch([stock('A', 5)])
    else:
        p['yesterday'].rows[0]['change'] = None
    assert relay_observation(p)['promotion'][0]['rate'] is None


def test_missing_streaks_not_assigned_to_first_board():
    p = pools()
    p['up'] = batch([stock('A', None), stock('B', 2)])
    p['yesterday'] = batch([stock('C', None), stock('D', 3)])
    r = relay_observation(p)
    assert r['ungraded_up'] == r['ungraded_previous'] == 1
    assert r['height'] is r['previous_height'] is None
    assert len(r['ladder']) == 1 and r['ladder'][0]['level'] == 2


def test_theme_ranking_uses_limit_participation_and_deduplicates_overlap():
    p = pools()
    p['up'] = batch([stock('A', 2), stock('B', 1)])
    market = batch([stock('A'), stock('B'), stock('C')])
    themes = [({'code':'T1','name':'Slow but broad','change':1}, batch([stock('A'), stock('B')])),
              ({'code':'T2','name':'Overlapping','change':8}, batch([stock('A'), stock('B')])),
              ({'code':'T3','name':'Lone gainer','change':12}, batch([stock('C')]))]
    r = theme_observation(market, batch([]), themes, p)['candidates']
    assert len(r) == 2
    assert r[0]['name'] == 'Slow but broad' and r[0]['limit_up'] == 2
    assert r[0]['first_boards'] == r[0]['relay_boards'] == 1
    assert r[0]['overlaps'] == ['Overlapping']
    assert r[0]['catalyst_verified'] is False


def test_partial_membership_and_other_market_are_not_confirmed():
    p = pools(); p['up'] = batch([stock('920001'), stock('A')])
    members = batch([stock('920001'), stock('A')]); members.status = 'partial'
    r = theme_observation(batch([stock('A')]), batch([]), [({'code':'T','name':'T','change':1}, members)], p)['candidates'][0]
    assert r['member_count'] == 1 and r['limit_up'] is None


def test_broad_access_labels_are_not_speculative_themes():
    b = batch([{'code':str(i),'name':name,'change':10-i,'amount':i} for i,name in enumerate(['融资融券','沪股通','MSCI中国','机器人','商业航天'])])
    assert {r['name'] for r in candidate_concepts(b)} == {'机器人','商业航天'}


def test_live_directory_screens_do_not_displace_narrative_candidates():
    screens = ['基金减仓', '标准普尔', '大盘股', '创业板综', '深成500', 'HS300_',
               '2026中报预增', '科技风格', '小盘成长', 'QFII重仓', '养老金', '近期新高']
    themes = ['CPO概念', '光通信模块', '央国企改革', '大基金持股']
    b = batch([{'code':str(i),'name':name,'change':100-i,'amount':10000-i}
               for i,name in enumerate(screens + themes)])
    assert {r['name'] for r in candidate_concepts(b)} == set(themes)


def bars():
    start = datetime(2026, 9, 1)
    return [{'date':(start+timedelta(days=i)).date().isoformat(),'close':100+i,'high':101+i} for i in range(25)]


def test_trends_exclude_future_bars_and_use_completed_series():
    b = bars()
    r = trend_structure(b+[{'date':'2026-10-01','close':9999,'high':9999}], b[-1]['date'])
    assert r['state'] == 'aligned'
    assert r['distance_ma20'] == pytest.approx((124/114.5-1)*100)
    assert r['drawdown20'] == pytest.approx((124/125-1)*100)


@pytest.mark.parametrize('fault,state', [('short','insufficient'),('duplicate','invalid'),('nonfinite','invalid'),('stale','stale')])
def test_invalid_or_stale_trend_series(fault,state):
    b=bars();day=b[-1]['date']
    if fault=='short': b=b[1:]
    elif fault=='duplicate': b[-1]['date']=b[-2]['date']
    elif fault=='nonfinite': b[-1]['close']=float('nan')
    else: day='2026-10-01'
    assert trend_structure(b,day)['state']==state


def test_trend_candidates_are_deduplicated_capacity_candidates():
    a,b,c=stock('A'),stock('B'),stock('C'); a['amount']=30;b['amount']=20;c['amount']=100
    members=[({'name':'One'},batch([a,b])),({'name':'Two'},batch([a]))]
    r=trend_candidates(batch([a,b,c]),members)
    assert [x['code'] for x in r]==['A','B']
    assert r[0]['themes']==['One','Two']


@pytest.mark.parametrize('clock,day',[('09:25','2026-11-10'),('09:40','2026-11-10'),('14:59','2026-11-10'),('15:00','2026-11-11')])
def test_intraday_bar_exclusion(clock,day):
    assert completed_day(datetime.fromisoformat('2026-11-11T'+clock+':00+08:00'))==day


def test_pool_clock_and_streak_validation():
    assert pool_clock(92500)=='09:25:00'
    assert pool_clock(0) is pool_clock(246000) is pool_clock(92500.5) is None
    assert positive_integer(2)==2
    assert positive_integer(1.5) is positive_integer(None) is positive_integer(-1) is None
