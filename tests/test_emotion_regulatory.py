"""Deterministic rule tests; synthetic prices are not market acceptance."""
from copy import deepcopy
from datetime import datetime
import json

from marketdata.short_term import TZ
from src.modules.short_term.regulatory import (extract_events, regulatory_windows, sessions,
    special_days, merge_events, dates_in)
from src.modules.short_term.exchange_events import parse_sse, exchange_events
from src.modules.short_term.regulatory_repository import RegulatoryRepository
from test_emotion_workbench import sessions as db_sessions, run_async

NOW=datetime(2026,11,14,9,tzinfo=TZ)
SYMBOL='600825.SH'


def history():
    rows=[{'date':d,'close':100.0} for d in sessions('2026-08-03','2026-11-13')]
    return {'rows':rows,'adjustment':'qfq'}, {'rows':deepcopy(rows),'adjustment':'none'}


def event(kind='ordinary',end='2026-11-11',effective='2026-11-12',**extra):
    return {'id':kind+end,'symbol':SYMBOL,'kind':kind,'period_start':end,'period_end':end,
        'effective_date':effective,'direction':'up','known_at':NOW.isoformat(),
        'authority':'issuer_disclosure',**extra}


def calc(events=(),stock=None,benchmark=None,coverage=None,known_at=None):
    a,b=history()
    return regulatory_windows(SYMBOL,stock or a,benchmark or b,'2026-11-13',events,
        coverage or {'status':'complete','gaps':[]},known_at=known_at or NOW.isoformat())


def doc(text,title='股票交易异常波动公告'):
    return {'status':'primary_text_verified','document_sha256':'hash','title':title,'text':text,
        'url':'https://static.cninfo.com.cn/example.pdf','observed_at':NOW.isoformat(),
        'published_at':'2026-11-14T00:00:00+08:00'}


def test_uses_all_suffixes_within_window_and_compounded_deviation():
    stock,bench=history()
    for r,v in zip(stock['rows'][-3:],[90,100,110]):r['close']=v
    w=calc(stock=stock,benchmark=bench)['windows'][0]
    assert w['status']=='calculated'
    assert w['upper_case']['sessions']==2
    assert w['upper_case']['deviation']==22.222222
    assert w['threshold_crossed'] is True
    assert [c['deviation'] for c in w['candidates']]==[10,22.222222,10]
    # 10% twice compounds to 21%; summing daily deviations is wrong.
    stock['rows'][-3]['close']=100;stock['rows'][-2]['close']=110;stock['rows'][-1]['close']=121
    assert calc(stock=stock)['windows'][0]['upper_case']['deviation']==21


def test_ordinary_reset_does_not_reset_severe_and_severe_does_not_reset_ordinary():
    ordinary,ten,thirty=calc([event()])['windows']
    assert ordinary['counted_dates']==['2026-11-12','2026-11-13']
    assert ten['reset_date'] is None and len(ten['counted_dates'])==10
    assert len(thirty['counted_dates'])==30
    windows=calc([event('severe')])['windows']
    assert windows[0]['reset_date'] is None
    assert all(w['reset_date']=='2026-11-12' for w in windows[1:])


def test_source_cutoff_duplicates_and_conflicting_versions():
    e=event();duplicate={**e,'id':'repeated','known_at':NOW.isoformat()}
    c=calc([e,duplicate])
    assert c['repeat_events']['up']==1
    assert len(c['reset_records'])==1
    assert calc([e],known_at='2026-11-13T23:59:00+08:00')['reset_records']==[]
    conflicting={**e,'id':'corrected','direction':'down'}
    c=calc([e,conflicting]);assert 'event_versions_conflict' in c['gaps']
    assert all(w['status']=='unavailable' for w in c['windows'])


def test_missing_scheduled_day_and_unadjusted_history_never_produce_clean_numbers():
    stock,bench=history();stock['rows'].pop(-2)
    assert calc(stock=stock)['windows'][0]['status']=='unavailable'
    stock,bench=history();stock['adjustment']='raw'
    assert 'corporate_action_adjustment_unverified' in calc(stock=stock)['gaps']
    assert calc(coverage={'status':'partial','gaps':[]})['windows'][0]['status']=='unavailable'


def test_disclosed_special_days_and_market_specific_delisting():
    days=sessions('2026-09-28','2026-10-14')
    assert '2026-10-10' not in days  # Makeup work Saturday is not an exchange session.
    assert '2026-10-01' not in days
    ipo=event('ipo',effective='2026-09-28');excluded,_,_=special_days([ipo],days,SYMBOL)
    assert list(excluded)==['2026-09-28','2026-09-29','2026-09-30','2026-10-08','2026-10-09']
    delist=event('delisting',effective='2026-10-08')
    assert len(special_days([delist],days,'600825.SH')[0])==1
    assert len(special_days([delist],days,'002242.SZ')[0])==5


def test_suspension_gap_is_distinct_from_missing_data_and_reorg_does_not_reset():
    stock,bench=history()
    es=[event('suspension',effective='2026-11-05',investigation=False),event('resumption',effective='2026-11-10',investigation=False)]
    stock['rows']=[r for r in stock['rows'] if not '2026-11-05'<=r['date']<'2026-11-10']
    c=calc(es,stock=stock)
    assert c['reset_records']==[]
    assert all(w['status']=='calculated' for w in c['windows'])
    assert c['special_days']['suspended']=={'2026-11-05':'suspended','2026-11-06':'suspended','2026-11-09':'suspended'}


def test_no_limit_and_ex_right_records_and_future_reset_are_explicit():
    text='公司股票于2026年11月13日不设涨跌幅限制。'
    events,gaps=extract_events(SYMBOL,[doc(text,'关于股票涨跌幅限制的公告')])
    assert not gaps and events[0]['kind']=='no_limit'
    assert calc(events)['windows'][0]['reason']=='no_eligible_current_session'
    text='除权（息）日：2026年11月13日。'
    events,gaps=extract_events(SYMBOL,[doc(text,'2026年权益分派实施公告')])
    assert not gaps and calc(events)['special_days']['ex_right']==['2026-11-13']
    c=calc([event(end='2026-11-13',effective='2026-11-16')])
    assert c['windows'][0]['reason']=='reset_pending_next_session'
    assert c['windows'][1]['status']=='calculated'


def test_issuer_parser_ignores_risk_predictions_and_historical_recounts():
    text='一、异常波动情况。公司股票连续三个交易日（2026年11月11日、12日、13日）收盘价格涨幅偏离值累计达到21%，属于异常波动。二、风险提示。2026年11月10日属于异常波动。'
    events,gaps=extract_events(SYMBOL,[doc(text)])
    assert not gaps and len(events)==1 and events[0]['period_end']=='2026-11-13'
    assert events[0]['authority']=='issuer_disclosure'
    pred=doc('公司股票连续三个交易日（2026年11月11日、12日、13日）涨幅偏离值可能超过20%，可能属于异常波动。')
    assert extract_events(SYMBOL,[pred])[0]==[]
    assert extract_events(SYMBOL,[doc(text,'股票交易异常波动更正公告')])[1][0]['reason']=='correction_requires_reconciliation'
    assert dates_in('2026年11月11日、12日、13日')==['2026-11-11','2026-11-12','2026-11-13']


def test_exchange_records_override_issuer_anchor_and_daily_dragon_board_is_not_reset():
    rows=[{'secCode':'600825','refType':'1','abnormalStart':'20261111','abnormalEnd':'20261112','tradeDate':'20261113'},
          {'secCode':'600825','refType':'12','abnormalStart':'20261113','abnormalEnd':'20261113','tradeDate':'20261113'}]
    es,gaps=parse_sse(SYMBOL,rows,NOW)
    assert not gaps and len(es)==1 and es[0]['effective_date']=='2026-11-16'
    assert es[0]['authority']=='exchange_publication'
    issuer=event(end='2026-11-12',effective='2026-11-13')
    merged=merge_events([issuer,*es]);assert len(merged)==1 and merged[0]['id']==es[0]['id']
    assert calc(merged,coverage={'status':'complete','exchange':{'status':'complete'}})['reset_verification']=='exchange_confirmed_history'
    _,gaps=parse_sse(SYMBOL,[{**rows[0],'refType':'UNKNOWN'}],NOW)
    assert gaps==['exchange_reason_unsupported']


@run_async
async def test_exchange_unsupported_feed_cannot_be_reported_as_empty_confirmation():
    result=await exchange_events('920001.BJ',NOW)
    assert result['status']=='unavailable' and result['gaps']


def test_append_only_versions_and_first_knowledge_survive_new_repository(db_sessions):
    e=event();new={**e,'known_at':'2026-11-16T09:00:00+08:00'}
    with db_sessions() as db:
        RegulatoryRepository(db).retain([e]);RegulatoryRepository(db).retain([new])
    with db_sessions() as db:
        r=RegulatoryRepository(db)
        assert r.read([SYMBOL],'2026-11-14T00:00:00+08:00')==[]
        assert r.read([SYMBOL],'2026-11-17T00:00:00+08:00')==[e]


def test_explicit_investigation_scope_resets_at_resumption_but_not_generic_reorg():
    text='本公司股票将于2026年11月13日开市起复牌。针对公司股票交易异常波动暨严重异常波动的情况，公司对有关事项进行了核查。'
    resumes,gaps=extract_events(SYMBOL,[doc(text,'停牌核查结果暨复牌公告')])
    assert not gaps and set(resumes[0]['reset_scopes'])=={'ordinary','severe'}
    es=[event(end='2026-11-06',effective='2026-11-09'),event('severe',end='2026-11-06',effective='2026-11-09'),
        event('suspension',effective='2026-11-10',investigation=True),*resumes]
    result=calc(es)
    assert all(w['reset_date']=='2026-11-13' for w in result['windows'])
    assert all(w['counted_dates']==['2026-11-13'] for w in result['windows'])
    assert result['reset_verification']=='pending_exchange_verification'


def test_szse_detail_period_and_publication_date_must_match():
    from src.modules.short_term.exchange_events import parse_szse
    import pytest
    row={'zqdm':'002242','dqrq':'2026-10-21','plyy':'异常期间价格涨幅偏离值累计达到21.18%'}
    detail={'zqjc':'九阳股份 (002242)','ycqj':'2026-10-20至2026-10-21','dqrq':'2026-10-21','plyy':row['plyy']}
    e=parse_szse('002242.SZ',row,detail,NOW,'https://www.szse.cn/api/report/ShowReport/data')
    assert e['effective_date']=='2026-10-22' and e['authority']=='exchange_publication'
    with pytest.raises(ValueError,match='date_invalid'):
        parse_szse('002242.SZ',row,{**detail,'dqrq':'2026-10-22'},NOW,e['source_url'])
