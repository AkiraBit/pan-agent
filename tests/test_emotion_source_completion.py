"""Boundary regressions; source-shaped fixtures are not live-market acceptance."""
from copy import deepcopy
from datetime import timedelta

import httpx
import pytest

from test_emotion_workbench import run_async
from test_emotion_regulatory import NOW, SYMBOL, calc, doc, event
from src.modules.short_term.regulatory import extract_events, reconcile_exchange_periods, document_role
from src.modules.short_term import exchange_events as exchange_module
from src.modules.short_term.exchange_events import parse_star


def test_calendar_conflicting_issuer_period_only_resolves_against_unique_exchange_record():
    source=doc('公司股票于2026年9月27日、9月28日连续两个交易日内收盘价格涨幅偏离值累计超过20%，属于股票交易异常波动。')
    source['published_at']='2026-09-29T00:00:00+08:00'
    events,issues=extract_events(SYMBOL,[source])
    assert not events and issues[0]['reason']=='issuer_period_calendar_conflict'
    official=event(end='2026-09-28',effective='2026-09-29',period_start='2026-09-24',authority='exchange_publication')
    remaining,resolved=reconcile_exchange_periods(issues,[official])
    assert not remaining and resolved[0]['period_start']=='2026-09-27'
    assert resolved[0]['official_period_start']=='2026-09-24'
    for other in [{**official,'authority':'issuer_disclosure'}, {**official,'direction':'down'}, {**official,'period_end':'2026-09-25'}]:
        assert reconcile_exchange_periods(issues,[other])[0]==issues
    assert reconcile_exchange_periods(issues,[official,{**official,'period_start':'2026-09-25'}])[0]==issues


def test_scanned_shareholder_response_does_not_create_an_issuer_event():
    reply=doc('新华传媒：有关异常波动的征询函已收悉。截至目前不存在应披露未披露重大事项。','关于股票交易异常波动情况的复函')
    reply['text_extraction']={'method':'ocr'}
    assert document_role(reply['title'])=='supporting_reply'
    assert extract_events(SYMBOL,[reply])==([],[])
    reply['title']='股票交易异常波动公告'
    events,issues=extract_events(SYMBOL,[reply])
    assert not events and issues[0]['reason']=='ocr_event_requires_corroboration'


def test_future_open_ended_halt_is_a_trading_constraint_not_missing_history():
    e=event(end='2026-11-13',effective='2026-11-16')
    hold=event('suspension',effective='2026-11-16',investigation=True,source_url='https://static.cninfo.com.cn/hold.pdf')
    result=calc([e,hold])
    assert not result['gaps']
    assert result['windows'][0]['reason']=='reset_pending_next_session'
    assert all(w['status']=='calculated' for w in result['windows'][1:])
    assert result['trading_constraints'][0]['kind']=='scheduled_suspension'
    assert result['trading_constraints'][0]['resumption_date'] is None
    assert result['reset_records'][0]['effective_date'] is None


def star_fixture(reason='5'):
    row={'SEC_CODE':'688801','SEC_ABBR':'科创测试','TYPE':reason,'TRADE_DATE':'20261111'}
    detail={'secCode':'688801','refType':reason,'tradeDate':'20261111','fileDate':'20261111',
            'unnormalStartDate':'20261109','unnormalEndDate':'20261111'}
    return row,detail


def test_star_ipo_prose_and_depositary_receipts_use_star_calendar_rules():
    from src.modules.short_term.abnormal import profile
    events,issues=extract_events('688801.SH',[doc('本公司股票将于2026年9月11日在上海证券交易所科创板上市。','首次公开发行股票科创板上市公告书提示性公告')])
    assert not issues and events[0]['effective_date']=='2026-09-11'
    assert events[0]['kind']=='ipo'
    assert profile('689009.SH')['ordinary_threshold']==30
    assert profile('689009.SH')['repeat_count_threshold']==3


@pytest.mark.parametrize('reason,kind,direction',[(str(i),'ordinary' if i<=6 else 'severe','up' if i%2 else 'down') for i in range(5,13)])
def test_star_uses_its_own_reason_codes_and_detail_period(reason,kind,direction):
    row,detail=star_fixture(reason);parsed=parse_star('688801.SH',row,[detail],NOW)
    assert (parsed['kind'],parsed['direction'])==(kind,direction)
    assert parsed['period_start']=='2026-11-09' and parsed['effective_date']=='2026-11-12'
    assert parsed['authority']=='exchange_publication'
    for bad in [{**detail,'secCode':'688002'},{**detail,'fileDate':'20261112'},{**detail,'unnormalEndDate':'20261113'}]:
        with pytest.raises(ValueError):parse_star('688801.SH',row,[bad],NOW)
    with pytest.raises(ValueError):parse_star('688801.SH',row,[],NOW)


@run_async
async def test_star_live_adapter_contract_paginates_filters_and_retains_raw(monkeypatch):
    row,detail=star_fixture();requests=[];real_client=httpx.AsyncClient
    def respond(request):
        requests.append(request)
        if request.url.path.endswith('commonQuery.do'):
            page=int(request.url.params['pageHelp.pageNo'])
            assert request.url.params['beginDate']=='20260806'
            rows=[{**row,'TYPE':'1'}] if page==1 else [row]
            return httpx.Response(200,json={'pageHelp':{'pageNo':page,'total':2},'result':rows})
        return httpx.Response(200,json={'pageHelp':{'data':[detail]}})
    monkeypatch.setattr(exchange_module.httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(respond),**kw))
    monkeypatch.setattr(exchange_module,'_cache',{})
    result=await exchange_module.exchange_events('688801.SH',NOW)
    assert result['status']=='complete' and len(result['events'])==1
    assert len(result['raw_pages'])==2 and len(result['raw_details'])==1 and len(requests)==3


@run_async
async def test_star_unknown_reason_and_schema_failures_never_clear_coverage(monkeypatch):
    row,_=star_fixture('99');real_client=httpx.AsyncClient
    monkeypatch.setattr(exchange_module.httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'pageHelp':{'pageNo':1,'total':1},'result':[row]})),**kw))
    monkeypatch.setattr(exchange_module,'_cache',{})
    result=await exchange_module.exchange_events('688801.SH',NOW)
    assert result['status']=='partial' and result['events']==[] and 'exchange_reason_unsupported' in result['gaps']
