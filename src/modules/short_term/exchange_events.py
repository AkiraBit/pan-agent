"""Exchange publication records, kept distinct from issuer announcements.

The SSE main-board query and reason codes are the ones published by its own
inquiry page. Unsupported/unreachable feeds are explicit gaps, never zero events.
"""
import asyncio
from datetime import datetime, timedelta
from hashlib import sha256
import json

import httpx
from marketdata.short_term import TZ
from .abnormal import EFFECTIVE
from .regulatory import trading_on_or_after

SSE_QUERY = 'https://query.sse.com.cn/commonSoaQuery.do'
SSE_PAGE = 'https://www.sse.com.cn/disclosure/diclosure/public/inquirydata/index.shtml'
# SSE search_diclosurePublic_2022.js, dataPackage("main"), current 2026 codes.
REASONS = {'1':('ordinary','up'), '2':('ordinary','down'),
           'Z3':('severe','up'), 'Z4':('severe','down'),
           'Z5':('severe','up'), 'Z6':('severe','down'),
           'Z7':('severe','up'), 'Z8':('severe','down')}
NON_RESET = {'11','12','13','14','15','41','42','51','52'}
_cache = {}


def parse_sse(symbol, rows, now):
    events, gaps = [], []
    for row in rows:
        if row.get('secCode') != symbol[:6]:
            gaps.append('exchange_subject_mismatch');continue
        reason = str(row.get('refType'))
        if reason not in REASONS:
            if reason not in NON_RESET:gaps.append('exchange_reason_unsupported')
            continue
        try:
            start, end, published = [datetime.strptime(row[k],'%Y%m%d').date().isoformat()
                                      for k in ('abnormalStart','abnormalEnd','tradeDate')]
            if start<EFFECTIVE:continue
            if not start<=end<=published<=now.astimezone(TZ).date().isoformat():raise ValueError()
        except (KeyError,ValueError,TypeError):
            gaps.append('exchange_event_date_invalid');continue
        kind,direction=REASONS[reason]
        raw=json.dumps(row,sort_keys=True,ensure_ascii=False)
        digest=sha256(raw.encode()).hexdigest()
        url='https://www.sse.com.cn/disclosure/diclosure/public/dailydata/detail.shtml?secCode='+symbol[:6]+'&refType='+reason+'&tradeDate='+row['tradeDate']
        events.append({'id':'exchange:'+digest[:24],'symbol':symbol,'kind':kind,'direction':direction,
            'period_start':start,'period_end':end,'exchange_publication_date':published,
            'effective_date':trading_on_or_after(published,strictly=True),
            'reset_basis':'exchange_publication_next_session','authority':'exchange_publication',
            'known_at':now.isoformat(),'published_at':published+'T00:00:00+08:00','date_precision':'day',
            'status':'exchange_confirmed','source_url':url,'document_sha256':digest,
            'document_title':'上海证券交易所交易公开信息 / '+reason,'excerpt':raw,'raw_record':row})
    return events,sorted(set(gaps))


async def exchange_events(symbol, now):
    if symbol.endswith('.SZ'):return await szse_events(symbol,now)
    if symbol.endswith('.SH') and symbol.startswith(('688','689')):return await star_events(symbol,now)
    day=now.astimezone(TZ).date();start=max(EFFECTIVE,(day-timedelta(days=100)).isoformat())
    result={'symbol':symbol,'status':'unavailable','events':[],'gaps':[],
            'range_start':start,'range_end':day.isoformat(),'source_url':SSE_PAGE,
            'observed_at':now.isoformat(),'raw_pages':[]}
    if not symbol.endswith('.SH'):
        result.update(source_url='https://www.szse.cn/disclosure/deal/public/' if symbol.endswith('.SZ') else SSE_PAGE,
                      gaps=['exchange_feed_not_available']);return result
    cached=_cache.get((symbol,day.isoformat()))
    if cached and 0<=(now-cached[0]).total_seconds()<600:return cached[1]
    try:
        async with httpx.AsyncClient(timeout=12,headers={'Referer':'https://www.sse.com.cn/','User-Agent':'Mozilla/5.0'}) as client:
            rows=[];complete=False
            for page in range(1,4):
                response=await client.get(SSE_QUERY,params={'sqlId':'JYGKXX_ZL','isPagination':'true',
                    'pageHelp.pageSize':100,'pageHelp.pageNo':page,'pageHelp.beginPage':page,
                    'pageHelp.endPage':page,'pageHelp.cacheSize':1,'tradeDateStart':start,
                    'tradeDateEnd':day.isoformat(),'secCode':symbol[:6],'refType':'','bsType':'','branchName':''})
                response.raise_for_status();body=response.json();help_=body['pageHelp']
                batch=body['result']
                if not isinstance(batch,list) or not isinstance(help_['total'],int):raise ValueError()
                result['raw_pages'].append(body);rows.extend(batch)
                if len(rows)>=help_['total']:complete=True;break
                if not batch:break
            result['events'],result['gaps']=parse_sse(symbol,rows,now)
            if not complete:result['gaps'].append('exchange_coverage_incomplete')
            result['status']='complete' if complete and not result['gaps'] else 'partial'
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        result['gaps'].append('exchange_feed_unavailable_or_schema_changed')
    _cache[(symbol,day.isoformat())]=(now,result)
    return result


STAR_PAGE = 'https://www.sse.com.cn/disclosure/diclosure/public/inquirydatatib/index.shtml'
STAR_QUERY = 'https://query.sse.com.cn/commonQuery.do'
STAR_DETAIL = 'https://query.sse.com.cn/marketdata/tradedata/queryKCBTradeInfo.do'
STAR_REASONS = {'5':('ordinary','up'),'6':('ordinary','down'),
                '7':('severe','up'),'8':('severe','down'),'9':('severe','up'),
                '10':('severe','down'),'11':('severe','up'),'12':('severe','down')}
STAR_NON_RESET = {'1','2','3','4','13','14','15','16'}


def parse_star(symbol, row, details, now):
    """The STAR list has no event interval; require its official detail record."""
    reason=str(row.get('TYPE'))
    if row.get('SEC_CODE')!=symbol[:6] or reason not in STAR_REASONS:
        raise ValueError('exchange_subject_or_reason_mismatch')
    matched=[d for d in details if d.get('secCode')==symbol[:6] and str(d.get('refType'))==reason
             and d.get('tradeDate')==row['TRADE_DATE']]
    if not matched or len(matched)!=len(details):raise ValueError('exchange_detail_identity_mismatch')
    periods={(d.get('unnormalStartDate'),d.get('unnormalEndDate'),d.get('fileDate')) for d in matched}
    if len(periods)!=1:raise ValueError('exchange_event_period_conflict')
    a,b,published=next(iter(periods))
    start,end,publication=[datetime.strptime(d,'%Y%m%d').date().isoformat() for d in (a,b,published)]
    if not EFFECTIVE<=start<=end<=publication<=now.astimezone(TZ).date().isoformat() or published!=row['TRADE_DATE']:
        raise ValueError('exchange_event_date_invalid')
    kind,direction=STAR_REASONS[reason]
    raw={'record':row,'details':details};digest=sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    url='https://www.sse.com.cn/disclosure/diclosure/public/dailydatatib/detail.shtml?secCode='+symbol[:6]+'&refType='+reason+'&tradeDate='+published
    return {'id':'exchange:'+digest[:24],'symbol':symbol,'kind':kind,'direction':direction,
        'period_start':start,'period_end':end,'exchange_publication_date':publication,
        'effective_date':trading_on_or_after(publication,strictly=True),'authority':'exchange_publication',
        'reset_basis':'exchange_publication_next_session','known_at':now.isoformat(),
        'published_at':publication+'T00:00:00+08:00','date_precision':'day','status':'exchange_confirmed',
        'source_url':url,'document_sha256':digest,'document_title':'上海证券交易所科创板交易公开信息 / '+reason,
        'excerpt':json.dumps(raw,ensure_ascii=False,sort_keys=True),'raw_record':raw}


async def star_events(symbol,now):
    day=now.astimezone(TZ).date();start=max(EFFECTIVE,(day-timedelta(days=100)).isoformat())
    result={'symbol':symbol,'status':'unavailable','events':[],'gaps':[],
            'range_start':start,'range_end':day.isoformat(),'source_url':STAR_PAGE,
            'observed_at':now.isoformat(),'raw_pages':[],'raw_details':[]}
    cached=_cache.get((symbol,day.isoformat()))
    if cached and 0<=(now-cached[0]).total_seconds()<600:return cached[1]
    try:
        async with httpx.AsyncClient(timeout=12,headers={'Referer':'https://www.sse.com.cn/','User-Agent':'Mozilla/5.0'}) as client:
            rows=[];complete=False
            for page in range(1,9):
                response=await client.get(STAR_QUERY,params={'sqlId':'COMMON_SSE_PL_JYXXPL_KCBJYGKXX_GGCX_L',
                    'isPagination':'true','pageHelp.pageSize':25,'pageHelp.pageNo':page,'pageHelp.beginPage':page,
                    'pageHelp.endPage':page,'pageHelp.cacheSize':1,'beginDate':start.replace('-',''),
                    'endDate':day.strftime('%Y%m%d'),'secCode':symbol[:6],'refType':'','deptName':'','txDirect':''})
                response.raise_for_status();body=response.json();meta=body['pageHelp'];batch=body['result']
                if not isinstance(batch,list) or not isinstance(meta['total'],int) or meta['pageNo']!=page:raise ValueError('exchange_schema_changed')
                result['raw_pages'].append(body);rows.extend(batch)
                if len(rows)>=meta['total']:complete=True;break
                if not batch:break
            seen=set()
            for row in rows:
                if row.get('SEC_CODE')!=symbol[:6]:raise ValueError('exchange_subject_mismatch')
                reason=str(row.get('TYPE'))
                if reason in STAR_NON_RESET:continue
                if reason not in STAR_REASONS:result['gaps'].append('exchange_reason_unsupported');continue
                key=(row.get('TRADE_DATE'),reason)
                if key in seen:continue
                seen.add(key)
                response=await client.get(STAR_DETAIL,params={'tradeDate':key[0],'secCode':symbol[:6],'refType':reason})
                response.raise_for_status();detail=response.json();result['raw_details'].append(detail)
                result['events'].append(parse_star(symbol,row,detail['pageHelp']['data'],now))
            if not complete:result['gaps'].append('exchange_coverage_incomplete')
            result['status']='complete' if complete and not result['gaps'] else 'partial'
    except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError) as exc:
        reason=str(exc);result['gaps'].append(reason if reason.startswith('exchange_') else 'exchange_feed_unavailable_or_schema_changed')
        result['status']='partial' if result['events'] else 'unavailable'
    _cache[(symbol,day.isoformat())]=(now,result)
    return result


async def collect_exchange_events(symbols,now):
    gate=asyncio.Semaphore(3)
    async def one(symbol):
        async with gate:return await exchange_events(symbol,now)
    return await asyncio.gather(*(one(s) for s in symbols))


SZSE_QUERY='https://www.szse.cn/api/report/ShowReport/data'
SZSE_PAGE='https://www.szse.cn/disclosure/deal/public/'


def parse_szse(symbol, row, detail, now, url):
    """Use the exchange's detail period, not the issuer's publication date."""
    import re
    from .regulatory import sessions
    if row.get('zqdm')!=symbol[:6] or symbol[:6] not in detail.get('zqjc',''):
        raise ValueError('exchange_subject_mismatch')
    dates=re.findall(r'20\d{2}-\d{2}-\d{2}',detail.get('ycqj',''))
    if len(dates)!=2:raise ValueError('exchange_event_date_invalid')
    a,b=dates;published=row['dqrq'];reason=detail['plyy']
    if not EFFECTIVE<=a<=b<=published<=now.astimezone(TZ).date().isoformat() or detail['dqrq']!=published:
        raise ValueError('exchange_event_date_invalid')
    if '严重' in reason or re.search(r'(10|30|十|三十)个?交易日|[三四34]次.*异常波动',reason):kind='severe'
    elif '异常期间' in reason and '偏离' in reason and 1<=len(sessions(a,b))<=3:kind='ordinary'
    else:raise ValueError('exchange_reason_unsupported')
    direction='down' if any(k in reason for k in ('跌幅','负向')) else 'up' if any(k in reason for k in ('涨幅','正向')) else 'unknown'
    if direction=='unknown':raise ValueError('exchange_reason_unsupported')
    raw=json.dumps({'record':row,'detail':detail},ensure_ascii=False,sort_keys=True);digest=sha256(raw.encode()).hexdigest()
    return {'id':'exchange:'+digest[:24],'symbol':symbol,'kind':kind,'direction':direction,
        'period_start':a,'period_end':b,'exchange_publication_date':published,
        'effective_date':trading_on_or_after(published,strictly=True),'authority':'exchange_publication',
        'reset_basis':'exchange_publication_next_session','known_at':now.isoformat(),
        'published_at':published+'T00:00:00+08:00','date_precision':'day','status':'exchange_confirmed',
        'source_url':url,'document_sha256':digest,'document_title':'深圳证券交易所交易公开信息 / '+reason,
        'excerpt':raw,'raw_record':{'record':row,'detail':detail}}


async def szse_events(symbol,now):
    import re
    from urllib.parse import parse_qs, urlparse
    day=now.astimezone(TZ).date();start=max(EFFECTIVE,(day-timedelta(days=100)).isoformat())
    result={'symbol':symbol,'status':'unavailable','events':[],'gaps':[],
            'range_start':start,'range_end':day.isoformat(),'source_url':SZSE_PAGE,
            'observed_at':now.isoformat(),'raw_pages':[],'raw_details':[]}
    cached=_cache.get((symbol,day.isoformat()))
    if cached and 0<=(now-cached[0]).total_seconds()<600:return cached[1]
    try:
        async with httpx.AsyncClient(timeout=12,headers={'Referer':SZSE_PAGE,'User-Agent':'Mozilla/5.0'}) as client:
            rows=[];complete=False
            for page in range(1,11):
                response=await client.get(SZSE_QUERY,params={'SHOWTYPE':'JSON','CATALOGID':'1842_xxpl_after',
                    'txtDMorJC':symbol[:6],'txtStart':start,'txtEnd':day.isoformat(),'PAGENO':page})
                response.raise_for_status();body=response.json();report=body[0];meta=report['metadata'];batch=report['data']
                if meta['catalogid']!='1842_xxpl_after' or not isinstance(batch,list) or meta['pageno']!=page:raise ValueError()
                result['raw_pages'].append(body);rows.extend(batch)
                if len(rows)>=meta['recordcount']:complete=True;break
                if not batch:break
            for row in rows:
                if row.get('zqdm')!=symbol[:6]:raise ValueError('exchange_subject_mismatch')
                reason=row.get('plyy','')
                # Daily movement, amplitude and turnover are not ordinary price
                # abnormality events. An unsupported abnormal reason stays a gap.
                if not any(k in reason for k in ('异常','连续','次出现')):continue
                match=re.search(r'a-param=[\'"]([^\'"]+)',row.get('bz',''))
                if not match:raise ValueError('exchange_detail_missing')
                query=parse_qs(urlparse(match[1]).query)
                if query.get('CATALOGID')!=['1842_detal'] or query.get('ZQDM')!=[symbol[:6]] or query.get('DQRQ')!=[row['dqrq']]:raise ValueError()
                # Reconstruct only the documented same-host detail request; never
                # follow an arbitrary URL or execute the supplied HTML/JavaScript.
                params={'SHOWTYPE':'JSON','CATALOGID':'1842_detal','TABKEY':'tab1,tab2',
                        'DQRQ':row['dqrq'],'ZQDM':symbol[:6],'ZBDM':query['ZBDM'][0]}
                response=await client.get(SZSE_QUERY,params=params);response.raise_for_status();body=response.json()
                result['raw_details'].append(body)
                result['events'].append(parse_szse(symbol,row,body[0]['data'][0],now,str(response.url)))
            if not complete:result['gaps'].append('exchange_coverage_incomplete')
            result['status']='complete' if complete and not result['gaps'] else 'partial'
    except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError) as exc:
        reason=str(exc)
        result['gaps'].append(reason if reason.startswith('exchange_') else 'exchange_feed_unavailable_or_schema_changed')
        result['status']='partial' if result['events'] else 'unavailable'
    _cache[(symbol,day.isoformat())]=(now,result)
    return result
