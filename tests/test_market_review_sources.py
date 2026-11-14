import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from src.modules.market import review_sources as s


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    s._cache.clear()
    s._pending.clear()
    monkeypatch.setattr(s, '_gate', asyncio.Semaphore(6))
    monkeypatch.setattr(s, 'now', lambda: datetime(2026, 11, 12, 16, tzinfo=s.CN))


def row(code='600001', **extra):
    return {'c': code, 'n': 'Example', 'p': 11000, 'zdp': 10, 'amount': 123000000,
            'hybk': '制造业', 'lbc': 2, 'fbt': 93001, 'lbt': 145000, 'zbc': 1, **extra}


def test_price_amount_and_timestamp_units():
    result = s.stock(row(fund=25000000), '2026-11-12', True)
    assert result['price'] == 11
    assert result['amount'] == 123000000
    assert result['seal_amount'] == 25000000
    assert result['first_limit_at'] == '2026-11-12T09:30:01+08:00'
    assert result['resealed']
    assert result['quote_at'] is None and result['themes'] == []


@pytest.mark.anyio
async def test_historical_pool_checks_unadjusted_close_not_server_qdate(monkeypatch):
    async def get(url, params, **kwargs):
        if 'eastmoney' in url:
            return {'rc': 0, 'data': {'tc': 1, 'qdate': 20261112, 'pool': [row()]}}
        if 'sina.cn' in url:
            return [{'day':'2026-11-11','open':'10','close':'11'}]
        assert params['param'] == 'sh600001,day,,,60,'
        return {'data': {'sh600001': {'day': [['2026-11-11', '10', '11']]}}}
    monkeypatch.setattr(s, 'get', get)
    assert len(await s.limit_pool('up', '2026-11-11')) == 1
    with pytest.raises(ValueError, match='independent daily close'):
        await s.limit_pool('up', '2026-11-10')
    with pytest.raises(ValueError, match='Future'):
        await s.limit_pool('up', '2026-11-13')


@pytest.mark.anyio
@pytest.mark.parametrize('rows,count', [([row()], 2), ([row(),row()], 2)])
async def test_incomplete_or_duplicate_pool_rejected(monkeypatch, rows, count):
    monkeypatch.setattr(s, 'get', AsyncMock(return_value={'rc': 0, 'data': {'qdate':20261112,'tc':count,'pool':rows}}))
    with pytest.raises(ValueError, match='Incomplete'):
        await s.limit_pool('up', '2026-11-12')


@pytest.mark.anyio
async def test_board_promotion_uses_yesterday_streak_and_unique_codes(monkeypatch):
    monkeypatch.setattr(s, 'trading_dates', AsyncMock(return_value=['2026-11-12']))
    async def pool(kind, day):
        return {'up':[row()], 'broken':[row('600002',lbc=None)],
                'yesterday':[row(ylbc=1),row('600002',ylbc=2),row('600003',ylbc=3)]}[kind]
    monkeypatch.setattr(s, 'limit_pool', pool)
    result = await s.board()
    assert (result['active_count'],result['opened_count'],result['seal_rate']) == (1,1,50)
    assert result['stocks'][1]['broken_board'] == 3
    assert result['fallen'][0]['broken_board'] == 4
    assert result['promotion'] == [{'label':'1→2','base':1,'promoted':1},{'label':'2→3','base':1,'promoted':0},{'label':'3→4','base':1,'promoted':0}]


@pytest.mark.anyio
async def test_latest_pool_failure_does_not_silently_roll_back_date(monkeypatch):
    monkeypatch.setattr(s, 'trading_dates', AsyncMock(return_value=['2026-11-12','2026-11-11']))
    monkeypatch.setattr(s, 'limit_pool', AsyncMock(side_effect=ValueError('unavailable')))
    with pytest.raises(ValueError):
        await s.board()


@pytest.mark.anyio
async def test_minute_refuses_other_day(monkeypatch):
    monkeypatch.setattr(s, 'get', AsyncMock(return_value={'data':{'sh600001':{'data':{'date':'20261112','data':[]}}}}))
    with pytest.raises(ValueError, match='different trading date'):
        await s.tencent_minute('600001','2026-11-11')


@pytest.mark.anyio
async def test_etf_aligns_16_funds_and_keeps_baseline_missing(monkeypatch):
    monkeypatch.setattr(s,'trading_dates',AsyncMock(return_value=['2026-11-12']))
    async def minute(code, day):
        return {'cumulative':[('09:30',100000000),('10:00',300000000)] + ([] if code==s.ETF_CODES[0] else [('10:01',400000000)])}
    monkeypatch.setattr(s,'minute',minute)
    result=await s.etf()
    assert result['amount']==48
    assert result['minutes']==[['09:30',16],['10:00',32]]
    assert result['windows'][0]['amount']==48
    assert result['windows'][0]['ratio'] is None and result['peak_window'] is None


def test_cffex_aggregates_contract_rank_columns_and_reported_changes():
    raw=('交易日,合约,排名,成交量排名,,,持买单量排名,,,持卖单量排名,,\n'
         '20261112,IF2611,1,其他,1,1,中信期货(代客),100,12,其他,4,2\n'
         '20261112,IF2611,2,其他,1,1,其他,100,12,中信期货(代客),150,-3\n'
         '20261112,IF2612,1,其他,1,1,中信期货(代客),50,4,中信期货(代客),70,8\n').encode('gb18030')
    assert s.parse_cffex(raw,'2026-11-12','IF')=={'long':150,'short':220,'net':-70,'net_change':11}
    with pytest.raises(ValueError,match='different trading date'):
        s.parse_cffex(raw,'2026-11-11','IF')
    with pytest.raises(ValueError,match='Empty'):
        s.parse_cffex(b'<html>unavailable</html>','2026-11-12','IF')


def test_lhb_deduplicates_reasons_preferring_daily():
    rows=[{'SECURITY_CODE':'1','EXPLANATION':'连续三个交易日','NET_BUY_AMT':300},
          {'SECURITY_CODE':'1','EXPLANATION':'日换手率20%','NET_BUY_AMT':100},
          {'SECURITY_CODE':'1','EXPLANATION':'日涨幅7%','NET_BUY_AMT':100}]
    assert sum(r['NET_BUY_AMT'] for r in s.single_day_rows(rows))==100


@pytest.mark.anyio
async def test_daily_partial_failure_preserves_other_modules(monkeypatch):
    monkeypatch.setattr(s,'trading_dates',AsyncMock(return_value=['2026-11-12']))
    monkeypatch.setattr(s,'lhb',AsyncMock(side_effect=ValueError('no disclosure')))
    monkeypatch.setattr(s,'futures',AsyncMock(return_value={'date':'2026-11-11'}))
    monkeypatch.setattr(s,'calendar',AsyncMock(return_value={'macro':[]}))
    result=await s.daily()
    assert result['lhb'] is None
    assert result['futures']['date']=='2026-11-11'
    assert result['errors']=={'lhb':'unavailable'}


@pytest.mark.anyio
async def test_http_cache_coalesces_and_never_forwards_user_credentials(monkeypatch):
    requests=[]
    async def handler(request):
        requests.append(request)
        await asyncio.sleep(.01)
        return httpx.Response(200,json={'ok':True})
    original=httpx.AsyncClient
    monkeypatch.setattr(s.httpx,'AsyncClient',lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs))
    values=await asyncio.gather(*(s.get('https://qt.gtimg.cn/example') for _ in range(8)))
    assert len(requests)==1 and all(v=={'ok':True} for v in values)
    assert 'authorization' not in requests[0].headers and 'cookie' not in requests[0].headers


def test_no_kanpanba_request_path_in_independent_adapter():
    from pathlib import Path
    source=Path(s.__file__).read_text()
    assert 'api.kanpanba.com' not in source and 'www.kanpanba.com' not in source


@pytest.mark.anyio
async def test_minute_falls_back_only_to_independent_provider(monkeypatch):
    monkeypatch.setattr(s,'eastmoney_minute',AsyncMock(side_effect=httpx.ConnectError('offline')))
    monkeypatch.setattr(s,'tencent_minute',AsyncMock(return_value={'date':'2026-11-12','sources':[s.PROVIDERS['tencent']]}))
    value=await s.minute('600001','2026-11-12')
    assert value['sources'][0]['id']=='tencent'


@pytest.mark.anyio
async def test_etf_snapshot_fallback_is_explicit_when_one_fund_fails(monkeypatch):
    monkeypatch.setattr(s,'trading_dates',AsyncMock(return_value=['2026-11-12']))
    monkeypatch.setattr(s,'minute',AsyncMock(side_effect=ValueError('unavailable')))
    fallback=AsyncMock(return_value={'status':'snapshot','minutes':[],'amount':100})
    monkeypatch.setattr(s,'etf_snapshot',fallback)
    result=await s.etf()
    assert result['status']=='snapshot' and result['minutes']==[]
    fallback.assert_awaited_once_with('2026-11-12')


@pytest.mark.anyio
async def test_five_minute_fallback_uses_requested_days_previous_close(monkeypatch):
    monkeypatch.setattr(s,'minute',AsyncMock(side_effect=ValueError('unavailable')))
    async def get(url, params, **kwargs):
        if 'mkline' in url:
            return {'data':{'sh600001':{'m5':[['202611111500','9','11'],['202611121500','11','12']]}}}
        return {'data':{'sh600001':{'day':[['2026-11-10','9','10'],['2026-11-11','10','11'],['2026-11-12','11','12']]}}}
    monkeypatch.setattr(s,'get',get)
    result=await s.stock_line('600001','2026-11-11')
    assert result['interval']=='5m' and len(result['line'])==1
    assert result['line'][0]['change_percent']==pytest.approx(10)
    with pytest.raises(ValueError,match='requested trading date'):
        await s.stock_line('600001','2026-11-09')


@pytest.mark.anyio
async def test_calendar_survives_tencent_daily_outage(monkeypatch):
    async def get(url, params, **kwargs):
        if 'gtimg' in url:
            raise httpx.ConnectError('Tencent unavailable')
        return [{'day':'2026-11-11','open':'3600','close':'3680.643'}, {'day':'2026-11-12','open':'3673','close':'3655.830'}]
    monkeypatch.setattr(s,'get',get)
    assert await s.trading_dates()==['2026-11-12','2026-11-11']


@pytest.mark.anyio
async def test_daily_bars_has_independent_tencent_fallback(monkeypatch):
    async def get(url, params, **kwargs):
        if 'sina.cn' in url:
            raise httpx.ConnectError('Sina unavailable')
        return {'data':{'sh000001':{'day':[['2026-11-12','3673','3655.83']]}}}
    monkeypatch.setattr(s,'get',get)
    assert (await s.daily_bars('sh000001'))[0][2]=='3655.83'
