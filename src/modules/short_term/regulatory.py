"""Source-derived event ledger and exchange-rule windows (2026-07-06 onward).

A numerical breach is never promoted to an exchange determination. Ordinary and
severe disclosures have separate reset histories. Unresolved dates, corrections
or incomplete source coverage are carried into every result, not guessed away.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
import re

from marketdata.short_term import TZ
from src.platform.scheduling.trading_calendar import calendar_known, is_trading_day
from .abnormal import EFFECTIVE, profile

DATE = re.compile(r'(?:(20\d{2})年)?(?:(\d{1,2})月)?(\d{1,2})日')
EVENT_TITLES = ('异常波动', '停牌', '复牌', '上市公告', '重新上市', '退市整理', '权益分派实施', '除权', '除息', '涨跌幅限制', '更正')


def document_role(title):
    # A shareholder's response is supporting evidence, not a new issuer event.
    if re.search(r'(?:复函|回函)$', title):
        return 'supporting_reply'
    return 'event_notice' if any(k in title for k in EVENT_TITLES) else 'risk_notice'


def sessions(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if b < a or (b-a).days > 500:
        return []
    days = [a+timedelta(days=n) for n in range((b-a).days+1)]
    if not all(calendar_known('CN', d) for d in days):
        return []
    return [d.isoformat() for d in days if is_trading_day('CN', d)]


def trading_on_or_after(day, *, strictly=False):
    d = date.fromisoformat(day) + timedelta(days=int(strictly))
    for _ in range(32):
        if not calendar_known('CN', d):
            return None
        if is_trading_day('CN', d):
            return d.isoformat()
        d += timedelta(days=1)
    return None


def dates_in(text, default_year=None):
    """Parse Chinese full/abbreviated date lists; never borrow the current year."""
    year, month = default_year, None
    result = []
    for match in DATE.finditer(text):
        if match[1]: year = int(match[1]); month = None
        if match[2]: month = int(match[2])
        if year and month:
            try: result.append(date(year, month, int(match[3])).isoformat())
            except ValueError: return []
    return list(dict.fromkeys(result))


def _event(symbol, kind, doc, excerpt, **fields):
    body = {'symbol': symbol, 'kind': kind, 'source_url': doc['url'],
            'document_sha256': doc['document_sha256'], 'document_title': doc['title'],
            'published_at': doc.get('published_at'), 'known_at': doc['observed_at'],
            'authority': 'issuer_disclosure', 'excerpt': excerpt[:1500], **fields}
    identity = {k:v for k,v in body.items() if k!='known_at'}
    body['id'] = 'reg:' + sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    return body


def extract_events(symbol, documents):
    events, unresolved = [], []
    for doc in documents:
        if doc.get('status') != 'primary_text_verified' or not doc.get('document_sha256'):
            continue
        title = doc['title']; text = re.sub(r'\s+', '', doc.get('text',''))
        if document_role(title)=='supporting_reply':
            continue
        if doc.get('text_extraction',{}).get('method')=='ocr':
            unresolved.append({'url':doc['url'],'reason':'ocr_event_requires_corroboration'})
            continue
        if title=='Provided primary source':title=text[:200]
        if not any(k in title for k in EVENT_TITLES):
            continue
        if any(k in title for k in ('更正', '取消', '撤销')):
            unresolved.append({'url':doc['url'],'reason':'correction_requires_reconciliation'})
            continue
        # Issuer-current description only. Historical references later in risk
        # sections do not create new events on the date of a repeated warning.
        intro = re.split(r'二[、.．]|二公司', text, maxsplit=1)[0][:6000]
        found = False
        if title=='Provided primary source':title=intro[:200]
        if '异常波动' in title:
            chunks = re.split(r'[。；]', intro)
            for kind, word in [('ordinary','异常波动'),('severe','严重异常波动')]:
                if kind=='severe' and '严重异常' not in title: continue
                candidates = []
                for chunk in chunks:
                    if word not in chunk or '偏离' not in chunk or not any(v in chunk for v in ('属于','达到','超过')):
                        continue
                    if kind=='ordinary' and '严重异常' in chunk: continue
                    if kind=='ordinary' and not re.search(r'连续[一二两三123]个?交易日|连续[一二两三123]天',chunk):continue
                    if any(v in chunk for v in ('可能','预计','若','未达到','未触及','不属于')): continue
                    published = doc.get('published_at')
                    dates = dates_in(chunk, datetime.fromisoformat(published).year if published else None)
                    if not dates or len(dates)>35: continue
                    if any(d < EFFECTIVE for d in dates): continue
                    end = max(dates); start = min(dates)
                    signed = re.search(r'偏离值累计(?:达到|超过|达|为)[+＋]?([-－]?\d+(?:\.\d+)?)%',chunk)
                    direction = ('down' if signed[1].startswith(('-', '－')) else 'up') if signed else 'down' if '收盘价格跌幅' in chunk or '收盘价跌幅' in chunk else 'up' if '涨幅偏离' in chunk else 'unknown'
                    days = sessions(start,end)
                    if not days or start not in days or end not in days:
                        issue={'url':doc['url'],'reason':'issuer_period_calendar_conflict','kind':kind,
                               'period_start':start,'period_end':end,'direction':direction,
                               'published_at':published,'document_sha256':doc['document_sha256'],'excerpt':chunk[:1500]}
                        if issue not in unresolved:unresolved.append(issue)
                        found=True
                        continue
                    candidates.append((start,end,direction,chunk))
                unique = {(a,b) for a,b,_,_ in candidates}
                if len(unique)==1 and doc.get('published_at'):
                    a,b,direction,chunk = candidates[-1]
                    directions={c for _,_,c,_ in candidates if c!='unknown'}
                    direction=next(iter(directions)) if len(directions)==1 else 'unknown'
                    published_day = datetime.fromisoformat(doc['published_at']).astimezone(TZ).date().isoformat()
                    if b <= published_day and (date.fromisoformat(published_day)-date.fromisoformat(b)).days <= 10:
                        events.append(_event(symbol,kind,doc,chunk,period_start=a,period_end=b,
                            effective_date=trading_on_or_after(b,strictly=True),direction=direction,
                            reset_basis='issuer_event_end_next_session_pending_exchange_publication',
                            status='disclosed'));found=True
        for kind, keyword in [('suspension','停牌'),('resumption','复牌')]:
            if keyword not in title:continue
            patterns = [rf'(?:公司股票|本公司股票|公司A股股票)[^。；]{{0,100}}?(?:自|于)(20\d{{2}}年\d{{1,2}}月\d{{1,2}}日)[^。；]{{0,55}}?{keyword}']
            matches = [m for p in patterns for m in re.finditer(p,text)]
            valid = [m for m in matches if not any(v in m[0] for v in ('预计','可能','不晚于','不停牌'))
                     and ('停牌' if kind=='resumption' else '复牌') not in m[0].split(m[1],1)[-1]]
            if kind=='resumption' and doc.get('published_at'):
                published_day=datetime.fromisoformat(doc['published_at']).date()
                valid=[m for m in valid if dates_in(m[1]) and abs((date.fromisoformat(dates_in(m[1])[0])-published_day).days)<=10]
            unique = {dates_in(m[1])[0] for m in valid if dates_in(m[1])}
            if len(unique)==1:
                day=next(iter(unique))
                scope_match=re.search(r'针对[^。；]{0,60}异常波动[^。；]{0,80}核查',text) if kind=='resumption' and '核查' in title else None
                scope_text=scope_match[0] if scope_match else ''
                scopes=(['severe'] if '严重异常波动' in scope_text else [])+(['ordinary'] if '异常波动' in scope_text.replace('严重异常波动','') else [])
                events.append(_event(symbol,kind,doc,valid[0][0]+('；'+scope_text if scope_text else ''),effective_date=day,
                    investigation=('核查' in title),reset_scopes=scopes,status='disclosed'));found=True
            elif kind=='resumption':
                unresolved.append({'url':doc['url'],'reason':'resumption_date_not_unambiguous'})
        special = [('ipo','上市公告',r'上市日期[：:为]*(20\d{2}年\d{1,2}月\d{1,2}日)'),
                   ('relisting','重新上市',r'(?:重新上市日期[：:为]*|于|自)(20\d{2}年\d{1,2}月\d{1,2}日)[^。；]{0,30}?(?:重新上市|上市交易)'),
                   ('delisting','退市整理',r'(?:于|自)(20\d{2}年\d{1,2}月\d{1,2}日)[^。；]{0,30}?(?:进入退市整理|在退市整理)'),
                   ('ex_right','权益分派实施',r'除权[（(]?[息）)]*日[：:为]*(20\d{2}年\d{1,2}月\d{1,2}日)')]
        for kind, keyword, pattern in special:
            if keyword not in title:continue
            matches=list(re.finditer(pattern,text))
            if kind=='ipo' and not matches:
                matches=list(re.finditer(r'股票(?:将)?于(20\d{2}年\d{1,2}月\d{1,2}日)[^。；]{0,40}?上市',text[:6000]))
            unique={dates_in(m[1])[0] for m in matches if dates_in(m[1])}
            if len(unique)==1:
                events.append(_event(symbol,kind,doc,matches[0][0],effective_date=next(iter(unique)),status='disclosed'));found=True
        if '涨跌幅限制' in title:
            matches=[c for c in re.split(r'[。；]',text) if '不设' in c and '涨跌幅限制' in c and not any(v in c for v in ('可能','预计','如','若'))]
            for chunk in matches:
                ds=dates_in(chunk)
                if len(ds)==1:
                    events.append(_event(symbol,'no_limit',doc,chunk,effective_date=ds[0],end_date=ds[0],status='disclosed'));found=True
        if '严重异常' in title and not any(e['kind']=='severe' and e['source_url']==doc['url'] for e in events):
            unresolved.append({'url':doc['url'],'reason':'severe_event_scope_not_unambiguous'})
        if not found:
            unresolved.append({'url':doc['url'],'reason':'event_date_or_scope_not_unambiguous'})
    # Repeated disclosure of the same event counts once. Keep corroborating sources.
    unique = {}
    for e in events:
        key=(e['kind'],e.get('period_start'),e.get('period_end'),e['effective_date'])
        if key not in unique:unique[key]=e
        else:unique[key].setdefault('corroborating_ids',[]).append(e['id'])
    return sorted(unique.values(),key=lambda e:(e['effective_date'] or '',e['kind'])), unresolved


def reconcile_exchange_periods(unresolved, exchange_events):
    """Resolve only a uniquely matched official period; preserve the bad claim.

    Do not guess a trading date, erase the issuer discrepancy, or reconcile a
    correction/unknown scope using an unrelated exchange event.
    """
    remaining, resolved = [], []
    for issue in unresolved:
        matches=[]
        if issue['reason']=='issuer_period_calendar_conflict' and issue.get('published_at'):
            published=datetime.fromisoformat(issue['published_at']).astimezone(TZ).date()
            matches=[e for e in exchange_events if e.get('authority')=='exchange_publication'
                     and e['kind']==issue['kind'] and e['period_end']==issue['period_end']
                     and e['direction']==issue['direction'] and issue['direction']!='unknown'
                     and 0<=(published-date.fromisoformat(e['period_end'])).days<=10]
        periods={(e['period_start'],e['period_end']) for e in matches}
        if len(periods)==1:
            resolved.append({**issue,'resolution':'exchange_period_preferred','exchange_event_ids':[e['id'] for e in matches],
                             'official_period_start':matches[0]['period_start'],'official_period_end':matches[0]['period_end']})
        else:remaining.append(issue)
    unique={}
    for item in resolved:
        key=(item['url'],item['kind'],item['period_start'],item['period_end'])
        if key in unique:unique[key].setdefault('additional_excerpts',[]).append(item['excerpt'])
        else:unique[key]=item
    return remaining,list(unique.values())


def merge_events(events):
    """Keep immutable source versions in storage, deduplicate in calculations.

    Exchange publication wins over a matching issuer claim; conflicting issuer
    versions remain flagged rather than silently overwriting historical facts.
    """
    groups={}
    versions_by_id={}
    for event in sorted(events,key=lambda e:e['known_at']):versions_by_id.setdefault(event['id'],event)
    for event in versions_by_id.values():
        key=(event['symbol'],event['kind'],event.get('period_end') or event.get('effective_date'))
        groups.setdefault(key,[]).append(event)
    merged=[]
    for versions in groups.values():
        ordered=sorted(versions,key=lambda e:(e.get('authority')=='exchange_publication',e['known_at']),reverse=True)
        chosen=dict(ordered[0]);chosen['corroborating_ids']=sorted(set(e['id'] for e in versions if e['id']!=chosen['id']))
        authoritative=[e for e in versions if e.get('authority')==chosen.get('authority')]
        # Different exchange reasons on the same end date are one severe event.
        signatures={(e.get('direction'), e.get('effective_date')) for e in authoritative}
        if len(signatures)>1:chosen['conflict']=True
        merged.append(chosen)
    return sorted(merged,key=lambda e:(e.get('effective_date') or '',e['kind']))


def special_days(events, days, symbol):
    excluded, suspended, rights = {}, {}, set()
    for e in events:
        kind=e['kind'];start=e.get('effective_date')
        if not start:continue
        if kind=='ipo':
            ipo_days=sessions(start,(date.fromisoformat(start)+timedelta(days=25)).isoformat())[:5]
            excluded.update({d:'ipo_first_five' for d in ipo_days if d in days})
        elif kind=='relisting' and start in days:excluded[start]='relisting_first_day'
        elif kind=='no_limit':
            excluded.update({d:'explicit_no_limit' for d in days if start<=d<=e.get('end_date',start)})
        elif kind=='delisting':
            # SZSE 4.5.6 excludes the entire delisting period. SSE's common rule
            # excludes no-limit days; do not silently import Shenzhen's rule.
            excluded.update({d:'delisting_period' if symbol.endswith('.SZ') else 'delisting_first_day'
                             for d in days if d>=start and (symbol.endswith('.SZ') or d==start)})
        elif kind=='suspension':
            resume=min((x['effective_date'] for x in events if x['kind']=='resumption' and x['effective_date']>=start),default=None)
            suspended.update({d:'suspended' for d in days if d>=start and (not resume or d<resume)})
        elif kind=='ex_right':rights.add(start)
    return excluded,suspended,rights


def regulatory_windows(symbol, stock, benchmark, as_of, events, coverage, *, known_at):
    rule=profile(symbol)
    cutoff=datetime.fromisoformat(known_at)
    events=merge_events([e for e in events if e['symbol']==symbol and datetime.fromisoformat(e['known_at'])<=cutoff])
    start=(date.fromisoformat(as_of)-timedelta(days=100)).isoformat()
    days=sessions(max(start,EFFECTIVE),as_of)
    excluded,suspended,rights=special_days(events,days,symbol)
    gaps=list(coverage.get('gaps',[]))
    if any(e.get('conflict') for e in events):gaps.append('event_versions_conflict')
    if coverage.get('status')!='complete':gaps.append('disclosure_coverage_incomplete')
    if not days:gaps.append('calendar_or_rule_version_unavailable')
    sr={r['date']:r for r in stock.get('rows',[]) if r['date']<=as_of}
    br={r['date']:r for r in benchmark.get('rows',[]) if r['date']<=as_of}
    # Adjusted closes are a declared provider convention, not official prices.
    if stock.get('adjustment')!='qfq':gaps.append('corporate_action_adjustment_unverified')
    resets=[]
    for e in events:
        if e['kind'] not in {'ordinary','severe'} or not e.get('effective_date'):continue
        effective=e['effective_date'];source_ids=[e['id']]
        # A linked investigation suspension can defer the start until resumption.
        holds=[x for x in events if x['kind']=='suspension' and x.get('investigation') and
               e['period_end']<=x['effective_date']<=effective]
        if holds:
            hold=max(holds,key=lambda x:x['effective_date'])
            resumes=[x for x in events if x['kind']=='resumption' and x.get('investigation') and x['effective_date']>=hold['effective_date']]
            if resumes:
                resume=min(resumes,key=lambda x:x['effective_date']);effective=resume['effective_date'];source_ids += [hold['id'],resume['id']]
            else:effective=None  # A disclosed open-ended halt is a constraint, not missing source coverage.
        resets.append({'event_id':e['id'],'scope':e['kind'],'period_end':e['period_end'],
            'effective_date':effective,'source_ids':source_ids,'authority':e.get('authority','issuer_disclosure'),
            'basis':e.get('reset_basis','exchange_publication_next_session'),
            'confirmation':'exchange_confirmed' if e.get('authority')=='exchange_publication' else 'issuer_disclosed_pending_exchange'})
    # Explicitly scoped investigation resumption is a separate rule anchor. A
    # generic corporate-action resumption is never promoted to a regulatory reset.
    for resume in events:
        if resume['kind']!='resumption' or not resume.get('reset_scopes'):continue
        holds=[h for h in events if h['kind']=='suspension' and h.get('investigation') and h['effective_date']<resume['effective_date']]
        hold=max(holds,key=lambda h:h['effective_date'],default=None)
        if not hold:
            gaps.append('investigation_resumption_unconfirmed');continue
        for scope in resume['reset_scopes']:
            linked=[e for e in events if e['kind']==scope and e.get('period_end','')<=hold['effective_date']]
            parent=max(linked,key=lambda e:e['period_end'],default=None)
            if not parent:
                gaps.append('resumption_reset_scope_unconfirmed');continue
            resets.append({'event_id':resume['id'],'scope':scope,'period_end':parent['period_end'],
                'effective_date':resume['effective_date'],'source_ids':[parent['id'],hold['id'],resume['id']],
                'authority':resume['authority'],'basis':'scoped_investigation_resumption_under_exchange_rule',
                'confirmation':'issuer_disclosed_pending_exchange'})
    windows=[]
    eligible=[d for d in days if d not in excluded and d not in suspended]
    for size,scope,up,down in [(3,'ordinary',rule['ordinary_threshold'],-rule['ordinary_threshold']),(10,'severe',100,-50),(30,'severe',200,-70)]:
        applicable=[r for r in resets if r['scope']==scope and r['period_end']<=as_of]
        anchor=max((r['effective_date'] for r in applicable if r['effective_date'] and r['effective_date']<=as_of),default=None)
        pending=any(r['effective_date'] is None or r['effective_date']>as_of for r in applicable)
        active=[d for d in eligible if not anchor or d>=anchor][-size:]
        row={'sessions':size,'scope':scope,'upper':up,'lower':down,'reset_date':anchor,'reset_event_ids':[r['event_id'] for r in applicable],
             'status':'unavailable','counted_dates':active,'excluded_dates':[{ 'date':d,'reason':reason} for d,reason in {**excluded,**suspended}.items() if d>=(active[0] if active else as_of)],'candidates':[]}
        if pending:row['reason']='reset_pending_next_session'
        elif not active or as_of not in eligible:row['reason']='no_eligible_current_session'
        elif gaps:row['reason']='source_or_adjustment_gap'
        else:
            for n in range(1,len(active)+1):
                selection=active[-n:]; base_candidates=[d for d in sr if d<selection[0] and d not in suspended]
                base=max(base_candidates,default=None)
                if not base:continue
                # Validate every scheduled day, including the pre-window base.
                calendar_days=sessions(base,as_of)
                if any(d not in sr or d not in br for d in calendar_days if d not in suspended):continue
                inputs=[]; stock_factor=index_factor=1.0; previous=base
                for d in calendar_days[1:]:
                    if d in suspended:continue
                    if d in selection:
                        if any(not math.isfinite(series[x]['close']) or series[x]['close']<=0 for series in (sr,br) for x in (previous,d)):
                            inputs=[];break
                        stock_factor*=sr[d]['close']/sr[previous]['close']
                        index_factor*=br[d]['close']/br[previous]['close']
                        inputs.append({'date':d,'base_date':previous,'stock_close':sr[d]['close'],'stock_base':sr[previous]['close'],
                                       'index_close':br[d]['close'],'index_base':br[previous]['close']})
                    previous=d
                if len(inputs)!=n:continue
                value=(stock_factor-index_factor)*100
                row['candidates'].append({'start':selection[0],'end':as_of,'base_date':base,'sessions':n,'deviation':round(value,6),'inputs':inputs})
            if row['candidates'] and len(row['candidates'])==len(active):
                upper=max(row['candidates'],key=lambda x:x['deviation']);lower=min(row['candidates'],key=lambda x:x['deviation'])
                row.update(status='calculated',upper_case=upper,lower_case=lower,upper_distance=round(up-upper['deviation'],6),lower_distance=round(lower['deviation']-down,6),threshold_crossed=upper['deviation']>=up or lower['deviation']<=down)
            else:row['reason']='missing_session_or_special_day_boundary'
        windows.append(row)
    ten=eligible[-10:];recent=[e for e in events if e['kind']=='ordinary' and e.get('period_end') in ten and e.get('direction') in {'up','down'}]
    severe_anchor=max((r['effective_date'] for r in resets if r['scope']=='severe' and r['effective_date'] and r['effective_date']<=as_of),default=None)
    recent=[e for e in recent if not severe_anchor or e['period_end']>=severe_anchor]
    repeat={'threshold':rule['repeat_count_threshold'],'up':sum(e['direction']=='up' for e in recent),'down':sum(e['direction']=='down' for e in recent),'event_ids':[e['id'] for e in recent],
            'exchange_confirmed_up':sum(e['direction']=='up' and e.get('authority')=='exchange_publication' for e in recent),
            'exchange_confirmed_down':sum(e['direction']=='down' and e.get('authority')=='exchange_publication' for e in recent),
            'status':'disclosed_events_only','official_determination':'unknown'}
    constraints=[]
    for hold in events:
        if hold['kind']!='suspension':continue
        resume=min((e['effective_date'] for e in events if e['kind']=='resumption' and e['effective_date']>=hold['effective_date']),default=None)
        if resume is None or resume>as_of:
            constraints.append({'kind':'scheduled_suspension' if hold['effective_date']>as_of else 'suspended',
                'start':hold['effective_date'],'resumption_date':resume,'source_url':hold['source_url'],'event_id':hold['id']})
    return {'symbol':symbol,**rule,'as_of':as_of,'known_at':known_at,'basis':'exchange_rules_with_source_derived_event_ledger',
            'status':'calculated_with_source_limits' if any(w['status']=='calculated' for w in windows) else 'unavailable',
            'windows':windows,'reset_records':resets,'events':events,'repeat_events':repeat,'coverage':coverage,'gaps':sorted(set(gaps)),
            'special_days':{'excluded':excluded,'suspended':suspended,'ex_right':sorted(rights)},'trading_constraints':constraints,
            'official_determination':'unknown','limits':['issuer_disclosure_is_not_exchange_publication_confirmation','no_inference_of_monitoring_clearance','turnover_and_discretionary_determinations_not_inferred'],
            'adjustment':stock.get('adjustment'),
            'price_basis':stock.get('price_basis',{}),
            'reset_verification':'exchange_confirmed_history' if coverage.get('exchange',{}).get('status')=='complete' and all(r['authority']=='exchange_publication' for r in resets) else 'pending_exchange_verification'}
