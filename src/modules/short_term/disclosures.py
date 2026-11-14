"""Fetch original issuer/exchange publications, with bounded, allowlisted reads.

Authenticating the original document is distinct from declaring that a stock is
or is not monitored. An empty search never clears a regulatory constraint.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import re
import subprocess
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from marketdata.short_term import TZ

HOSTS = {'www.cninfo.com.cn', 'static.cninfo.com.cn', 'www.sse.com.cn', 'static.sse.com.cn',
         'www.szse.cn', 'disc.static.szse.cn', 'docs.static.szse.cn'}
KEYWORDS = ('异常波动', '严重异常', '重点监控', '停牌', '复牌', '监管措施', '风险提示',
            '上市公告', '重新上市', '退市整理', '权益分派实施', '除权', '除息', '涨跌幅限制', '更正')
DOCUMENT_LIMIT = 32
_gate = asyncio.Semaphore(4)
_cache = {}


def official_url(url):
    try:
        p = urlparse(url or '')
        return p.scheme == 'https' and p.hostname in HOSTS and not p.username and not p.password and p.port in (None, 443)
    except ValueError:
        return False


def pdf_text(raw):
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted or len(reader.pages) > 120:
        raise ValueError('document_not_readable')
    return '\n'.join((p.extract_text() or '') for p in reader.pages)[:80000]


async def original(client, url):
    for _ in range(3):
        if not official_url(url):
            raise ValueError('non_primary_source')
        async with client.stream('GET', url, follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                from urllib.parse import urljoin
                url = urljoin(url, r.headers.get('location', ''))
                continue
            r.raise_for_status()
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body.extend(chunk)
                if len(body) > 8_000_000:
                    raise ValueError('document_too_large')
        raw = bytes(body)
        extraction = {'method': 'embedded_text'}
        if raw.startswith(b'%PDF'):
            text = await asyncio.to_thread(pdf_text, raw)
            if len(text.strip()) < 40:
                from src.platform.marketdata.document_ocr import recognize_pdf
                text, extraction = await asyncio.to_thread(recognize_pdf, raw)
        else:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()
            text = soup.get_text(' ', strip=True)[:80000]
        if len(text.strip()) < 40:
            raise ValueError('document_text_missing')
        return text, hashlib.sha256(raw).hexdigest(), url, extraction
    raise ValueError('redirect_limit')


def relevant_excerpt(text, code, name):
    compact = re.sub(r'\s+', '', text)
    if code not in compact and (not name or name not in compact):
        raise ValueError('document_subject_mismatch')
    parts = re.split(r'(?<=[。；\n])', text)
    excerpts = [p.strip() for p in parts if any(k in p for k in KEYWORDS)]
    return '\n'.join(excerpts)[:6000] or text[:2000]


async def stock_disclosures(symbol, now, supplied_urls=()):
    day = now.astimezone(TZ).date()
    key = (symbol, day.isoformat(), tuple(supplied_urls))
    cached = _cache.get(key)
    if cached and 0 <= (now - cached[0]).total_seconds() < 600:
        return cached[1]
    code = symbol[:6]
    result = {'symbol': symbol, 'documents': [], 'search_status': 'unavailable',
              'monitoring_status': 'unknown', 'reason': 'no_verified_monitoring_determination',
              'observed_at': now.isoformat(), 'range_start': (day-timedelta(days=100)).isoformat()}
    async with _gate, httpx.AsyncClient(timeout=12, headers={
        'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.cninfo.com.cn/'}) as client:
        candidates = []
        name = ''
        complete = False
        try:
            response = await client.post('https://www.cninfo.com.cn/new/information/topSearch/query',
                                         data={'keyWord': code, 'maxNum': '10'})
            response.raise_for_status()
            stock = next(x for x in response.json() if x.get('code') == code and x.get('category') == 'A股')
            name = stock.get('zwjc') or ''
            result['name'] = name
            complete = False
            announcements = []
            for page in range(1, 4):
                response = await client.post('https://www.cninfo.com.cn/new/hisAnnouncement/query', data={
                    'pageNum': str(page), 'pageSize': '30', 'column': 'sse' if symbol.endswith('.SH') else 'szse',
                    'tabName': 'fulltext', 'stock': code + ',' + stock['orgId'],
                    'seDate': result['range_start'] + '~' + day.isoformat(), 'sortName': 'time',
                    'sortType': 'desc', 'isHLtitle': 'false'})
                response.raise_for_status()
                data = response.json()
                announcements.extend(data.get('announcements') or [])
                if not data.get('hasMore'):
                    complete = True
                    break
            result['search_status'] = 'complete' if complete else 'partial'
            result['searched_count'] = len(announcements)
            for a in announcements:
                title = re.sub('<[^>]+>', '', a.get('announcementTitle') or '')
                published = datetime.fromtimestamp(a['announcementTime']/1000, TZ)
                # First observed now; never backdate a date-only item's availability.
                if published > now:
                    continue
                if a.get('secCode') == code and any(k in title for k in KEYWORDS):
                    candidates.append({'title': title, 'url': 'https://static.cninfo.com.cn/' + a['adjunctUrl'],
                                       'published_at': published.isoformat(), 'date_precision': 'day'})
        except (httpx.HTTPError, ValueError, KeyError, TypeError, StopIteration):
            result['search_status'] = 'unavailable'
        result['matched_document_count'] = len(candidates)
        result['document_limit'] = DOCUMENT_LIMIT
        from .regulatory import document_role
        for candidate in candidates:
            candidate['document_role'] = document_role(candidate['title'])
        critical = [c for c in candidates if c['document_role']=='event_notice']
        warnings = [c for c in candidates if c not in critical]
        result['event_document_count'] = len(critical)
        selected = critical[:DOCUMENT_LIMIT]
        result['event_documents_complete'] = complete and len(selected) == len(critical)
        candidates = selected + warnings[:max(0, DOCUMENT_LIMIT-len(selected))]
        candidates += [{'title': 'Provided primary source', 'url': u, 'published_at': None,
                        'date_precision': 'unknown'} for u in supplied_urls[:3] if official_url(u)]
        seen = set()
        for item in candidates:
            if item['url'] in seen:
                continue
            seen.add(item['url'])
            doc = {**item, 'status': 'unavailable'}
            try:
                text, digest, url, extraction = await original(client, item['url'])
                excerpt = relevant_excerpt(text, code, name)
                doc.update(url=url, status='primary_text_verified', text=text, excerpt=excerpt,
                           document_sha256=digest, observed_at=now.isoformat(),
                           text_extraction=extraction,
                           tags=[k for k in KEYWORDS if k in item['title']],
                           verification='original_document_subject_with_ocr' if extraction['method']=='ocr' else 'original_document_and_subject_only')
            except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError, PyPdfError, subprocess.SubprocessError) as exc:
                doc['reason'] = str(exc) if isinstance(exc, ValueError) and len(str(exc)) < 80 else 'original_unreadable_or_subject_mismatch'
            result['documents'].append(doc)
    # Preserve a discovered original, but do not manufacture a clean monitoring status.
    _cache[key] = (now, result)
    return result


async def collect_disclosures(symbols, now, supplied_urls=()):
    return await asyncio.gather(*(stock_disclosures(s, now, supplied_urls) for s in symbols[:12]))
