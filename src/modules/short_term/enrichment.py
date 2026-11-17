"""Add primary documents and reproducible rule calculations to frozen facts."""
import asyncio
from datetime import datetime
from hashlib import sha256

from marketdata.sentiment import daily_series
from marketdata.short_term import TZ
from .abnormal import profile, reference_windows
from .disclosures import collect_disclosures, DOCUMENT_LIMIT
from .regulatory import extract_events, regulatory_windows, merge_events, reconcile_exchange_periods, document_role
from .exchange_events import collect_exchange_events
from .facts import evidence, utc_now


async def enrich_facts(facts, inputs):
    symbols = list(dict.fromkeys([*inputs['settings'].get('focus_symbols', []),
                                 *[q['symbol'] for q in facts['quotes']]]))[:9]
    now = datetime.fromisoformat(facts['collected_at'])
    urls = [n['source_url'] for n in inputs.get('notes', []) if n.get('source_url')]
    keys = list(dict.fromkeys([*symbols, *[profile(s)['benchmark'] for s in symbols]]))
    gate = asyncio.Semaphore(4)

    async def daily(symbol):
        async with gate:
            return await asyncio.to_thread(daily_series, symbol)
    documents, exchange, histories = await asyncio.gather(collect_disclosures(symbols, now, urls), collect_exchange_events(symbols, now),
                                               asyncio.gather(*(daily(s) for s in keys)))
    histories = dict(zip(keys, histories))
    exchange = {x["symbol"]:x for x in exchange}
    calculations = [reference_windows(s, histories[s], histories[profile(s)['benchmark']],
                                     facts['reference_trade_date']) for s in symbols]
    facts['regulatory'] = []
    facts['regulatory_events'] = []
    facts['regulatory_windows'] = []
    for item in documents:
        visible = {k:v for k,v in item.items() if k!='documents'}
        visible['document_ids'] = []
        for doc in item['documents']:
            identity = 'primary:' + sha256(doc['url'].encode()).hexdigest()[:20]
            visible['document_ids'].append(identity)
            facts['evidence'].append(evidence(identity, 'primary_document', doc['title'], 'cninfo/official',
                {k:v for k,v in doc.items() if k not in {'text','url','title'}}, now,
                published=doc.get('published_at'), url=doc['url'], status=doc['status']))
        facts['regulatory'].append(visible)
        events, unresolved = extract_events(item['symbol'], item['documents'])
        unresolved,reconciliations = reconcile_exchange_periods(unresolved, exchange[item['symbol']]['events'])
        prior = [e for e in inputs.get('regulatory_memory', []) if e['symbol']==item['symbol']]
        original_events = [*prior, *events, *exchange[item['symbol']]['events']]
        events = merge_events(original_events)
        facts['regulatory_events'].extend(original_events)
        coverage = {'status': 'complete' if item.get('event_documents_complete') and not unresolved and
                    all(d['status']=='primary_text_verified' for d in item['documents'] if document_role(d['title'])=='event_notice') else 'partial',
                    'range_start': item['range_start'], 'range_end': now.astimezone(TZ).date().isoformat(),
                    'source': 'cninfo_issuer_disclosures', 'unresolved': unresolved, 'reconciliations':reconciliations,
                    'supporting_documents_unavailable':sum(d['status']!='primary_text_verified' for d in item['documents'] if document_role(d['title'])!='event_notice'),
                    'gaps': sorted(set(u['reason'] for u in unresolved)), 'search_status':item['search_status'],
                    'event_document_count':item.get('event_document_count',0), 'document_limit':DOCUMENT_LIMIT,
                    'exchange': {k:v for k,v in exchange[item['symbol']].items() if k not in {'events','raw_pages','raw_details'}}}
        calc = regulatory_windows(item['symbol'], histories[item['symbol']], histories[profile(item['symbol'])['benchmark']],
                                  facts['reference_trade_date'], events, coverage, known_at=now.isoformat())
        facts['regulatory_windows'].append(calc)
        facts['evidence'].append(evidence('regulatory:'+item['symbol'], 'regulatory_window',
            item['symbol']+' / Source-anchored regulatory windows', 'panwatch+exchange_rules+primary_documents',
            calc, now, url=calc['source_url'], status=calc['status']))
    for calc in calculations:
        facts['evidence'].append(evidence('abnormal:' + calc['symbol'], 'abnormal_calculation',
            calc['symbol'] + ' / 2026 deviation windows', 'panwatch+exchange_rules', calc, now,
            url=calc['source_url'], status=calc['status']))
    facts['abnormal'] = calculations
    facts.setdefault('raw', {})['primary_documents'] = documents
    facts['raw']['daily_histories'] = histories
    facts['raw']['exchange_publications'] = exchange
    facts['capabilities'].update(abnormal_window=any(c['status']=='reference_only' for c in calculations),
                                 regulatory_monitoring=any(d['status']=='primary_text_verified' for s in documents for d in s['documents']))
    facts['evidence'] = [e for e in facts['evidence'] if e['id']!='capability:constraints']
    facts['evidence'].append(evidence('capability:constraints','capability','Verification coverage','panwatch',
        {'capabilities':facts['capabilities'], 'regulatory_status':'original_text_is_not_a_clean_monitoring_verdict',
         'abnormal_status':'source-derived regulatory ledger and scoped resets; exchange determination remains separate',
         'auction_status':'requires_enabled_fuyao_auction_source'}, now))
    facts['collected_at'] = utc_now().isoformat()
    facts['verification_scope'] = {'symbols': symbols, 'max_documents_per_symbol': DOCUMENT_LIMIT, 'history_sessions': 80}
    return facts
