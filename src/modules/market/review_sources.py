"""Independent public sources for the review dashboard.

No Kanpanba requests. Units and dates are checked at provider boundaries. Missing
measurements stay missing; provider industry/ETF classifications are not themes.
"""
from __future__ import annotations

import asyncio
import csv
import io
import math
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

CN = ZoneInfo('Asia/Shanghai')
NY = ZoneInfo('America/New_York')
PROVIDERS = {
    'eastmoney': {'id': 'eastmoney', 'name': '东方财富', 'url': 'https://data.eastmoney.com/ztb/detail'},
    'sina': {'id': 'sina', 'name': '新浪财经', 'url': 'https://finance.sina.com.cn/'},
    'tencent': {'id': 'tencent', 'name': '腾讯证券', 'url': 'https://gu.qq.com/'},
    'cffex': {'id': 'cffex', 'name': '中国金融期货交易所', 'url': 'http://www.cffex.com.cn/ccpm/'},
    'yahoo': {'id': 'yahoo', 'name': 'Yahoo Finance', 'url': 'https://finance.yahoo.com/'},
    'baidu': {'id': 'baidu', 'name': '百度股市通', 'url': 'https://finance.baidu.com/calendar'},
}
ETF_CODES = ('510300','510310','510330','159919','510050','510500','159922','512100',
             '159845','588000','588080','159915','512050','563360','159338','159352')
SECTORS = (('SOXX','半导体'),('IGV','软件'),('SKYY','云计算'),('CIBR','网络安全'),
           ('AIQ','人工智能'),('BOTZ','机器人'),('ARKQ','自动化'),('CARZ','汽车'),
           ('LIT','锂电池'),('TAN','光伏'),('ICLN','清洁能源'),('ITA','航空军工'),
           ('XBI','生物科技'),('IHI','医疗器械'),('XLV','医疗保健'),('XLF','金融'),
           ('KRE','区域银行'),('XLK','科技'),('XLY','可选消费'),('XLP','必选消费'),
           ('XLE','能源'),('XLB','材料'),('XLI','工业'),('XLU','公用事业'))
_cache: OrderedDict[tuple, tuple[float, object]] = OrderedDict()
_pending: dict[tuple, asyncio.Task] = {}
_gate = asyncio.Semaphore(6)


def now():
    return datetime.now(CN)


def provenance(*ids, method=None):
    return {'sources': [PROVIDERS[i] for i in ids], 'method': method}


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Missing numeric measurement')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite measurement')
    return result


def optional(value):
    try:
        return number(value)
    except (ValueError, TypeError):
        return None


async def get(url, params=None, *, ttl=30, raw=False):
    key = (url, tuple(sorted((params or {}).items())), raw)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < ttl:
        return cached[1]

    async def request():
        try:
            async with _gate:
                async with httpx.AsyncClient(timeout=10, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/plain,*/*', **({'Referer': 'https://quote.eastmoney.com/'} if 'eastmoney.com/' in url else {})}) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    value = response.content if raw else response.json()
            _cache[key] = (time.monotonic(), value)
            _cache.move_to_end(key)
            while len(_cache) > 512:
                _cache.popitem(last=False)
            return value
        finally:
            _pending.pop(key, None)
    if key not in _pending:
        _pending[key] = asyncio.create_task(request())
    return await asyncio.shield(_pending[key])


async def daily_bars(symbol):
    try:
        value = await get('https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData',
                          {'symbol': symbol, 'scale': 240, 'ma': 'no', 'datalen': 60}, ttl=300)
        if not isinstance(value, list) or not value:
            raise ValueError('Missing Sina daily bars')
        bars = [[r['day'][:10], r['open'], r['close']] for r in value]
        for row in bars:
            datetime.strptime(row[0], '%Y-%m-%d')
            number(row[2])
        return bars
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        value = await get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                          {'param': f'{symbol},day,,,60,'}, ttl=300)
        return value['data'][symbol]['day']


async def trading_dates():
    bars = await daily_bars('sh000001')
    dates = sorted({datetime.strptime(row[0], '%Y-%m-%d').date().isoformat() for row in bars}, reverse=True)
    # The public limit pools retain recent dates only; never advertise unsupported years.
    cutoff = (now().date() - timedelta(days=25)).isoformat()
    dates = [day for day in dates if cutoff <= day <= now().date().isoformat()][:15]
    if now().strftime('%H:%M') < '09:25':
        dates = [d for d in dates if d < now().date().isoformat()]
    if not dates:
        raise ValueError('Missing trading dates')
    return dates


async def limit_pool(kind, day):
    if day > now().date().isoformat():
        raise ValueError('Future trading date')
    methods = {'up': 'getTopicZTPool', 'broken': 'getTopicZBPool', 'yesterday': 'getYesterdayZTPool'}
    value = await get('https://push2ex.eastmoney.com/' + methods[kind], {
        'ut': '7eea3edcaed734bea9cbfc24409ed989', 'dpt': 'wz.ztzt', 'Pageindex': 0,
        'pagesize': 10000, 'sort': 'zs:desc' if kind == 'yesterday' else 'fbt:asc', 'date': day.replace('-', '')},
        ttl=30 if day == now().date().isoformat() else 21600)
    data = value.get('data')
    if value.get('rc') != 0 or not isinstance(data, dict) or not data.get('qdate'):
        raise ValueError('Missing pool or different trading date')
    rows = data.get('pool')
    if not isinstance(rows, list) or len(rows) != data.get('tc') or len({r['c'] for r in rows}) != len(rows):
        raise ValueError('Incomplete limit pool')
    if day < now().date().isoformat() and rows :
        # qdate is the server's current quote date even for historical pools.
        # Check one historical close against an independent unadjusted daily bar.
        sample = rows[0]
        symbol = cn_symbol(sample['c'])
        bars = await daily_bars(symbol)
        match = next((bar for bar in bars if bar[0] == day), None)
        if not match or abs(number(match[2]) - number(sample['p'])/1000) > .011:
            raise ValueError('Historical pool does not match independent daily close')
    return rows


def limit_time(day, value):
    if not value:
        return None
    value = str(value).zfill(6)
    return datetime.strptime(day + value, '%Y-%m-%d%H%M%S').replace(tzinfo=CN).isoformat()


def stock(row, day, active=None, previous=0):
    result = {'code': row['c'], 'name': row['n'], 'price': number(row['p']) / 1000,
              'change_percent': number(row['zdp']), 'industry': row.get('hybk'), 'group': row.get('hybk'),
              'amount': optional(row.get('amount')), 'float_cap': optional(row.get('ltsz')),
              'turnover_rate': optional(row.get('hs')), 'board_count': int(row.get('lbc') or previous + 1),
              'first_limit_at': limit_time(day, row.get('fbt')), 'last_limit_at': limit_time(day, row.get('lbt')),
              'open_count': row.get('zbc'), 'seal_amount': optional(row.get('fund')),
              'resealed': active is True and (row.get('zbc') or 0) > 0,
              # Pool API supplies the trading date, not a per-stock exchange quote timestamp.
              'quote_at': None, 'trade_date': day, 'line': [], 'themes': [], 'themes_date': None}
    if active is not None:
        result['active'] = active
    if not active and previous:
        result['broken_board'] = previous + 1
    return result


async def board(date=None):
    dates = await trading_dates()
    day = date or dates[0]
    if day not in dates:
        raise ValueError('Date outside available pool history')
    up, broken = await asyncio.gather(limit_pool('up', day), limit_pool('broken', day))
    extras = await asyncio.gather(limit_pool('yesterday', day), return_exceptions=True)
    previous = extras[0] if isinstance(extras[0], list) else []
    prev = {r['c']: int(r.get('ylbc') or 1) for r in previous}
    rows = [stock(r, day, True) for r in up] + [stock(r, day, False, prev.get(r['c'], 0)) for r in broken]
    seen = {r['code'] for r in rows}
    closed = day < now().date().isoformat() or now().strftime('%H:%M') >= '15:00'
    failed = [stock(r, day, previous=prev[r['c']]) for r in previous if r['c'] not in seen]
    for row in failed:
        row['state'] = 'fallen' if closed else 'waiting'
    historical_dates = [d for d in dates if d <= day][:10]
    historical = await asyncio.gather(*(limit_pool('up', d) for d in historical_dates), return_exceptions=True)
    history = [{'date': d, 'sealed': len(r), 'total': len(r), 'highest': max((x.get('lbc', 1) for x in r), default=0)}
               for d, r in zip(historical_dates, historical) if isinstance(r, list)]
    heights = sorted(set(prev.values()))
    sealed_codes = {r['c'] for r in up}
    promotion = [{'label': f'{h}→{h+1}', 'base': sum(v == h for v in prev.values()),
                  'promoted': sum(c in sealed_codes and v == h for c, v in prev.items())} for h in heights]
    errors = {}
    if isinstance(extras[0], Exception):
        errors['promotion'] = 'unavailable'
    if len(history) != len(historical_dates):
        errors['history'] = 'partial'
    return {'date': day, 'market_status': '已收盘' if closed else '盘中', 'available': True,
            'stocks': rows, 'fallen': failed if closed else [], 'waiting': [] if closed else failed, 'watch': [],
            'total_count': len(rows), 'active_count': len(up), 'opened_count': len(broken),
            'seal_rate': round(100*len(up)/len(rows), 1) if rows else None, 'observed_at': now().isoformat(),
            'history': list(reversed(history)), 'promotion': promotion, 'errors': errors,
            **provenance('eastmoney','sina','tencent', method='eastmoney_pool')}


def cn_symbol(code):
    return ('sh' if code.startswith(('5', '6', '9')) and not code.startswith('92') else 'sz' if code.startswith(('0','1','2','3')) else 'bj') + code


async def tencent_minute(code, day):
    symbol = cn_symbol(code)
    value = await get('https://web.ifzq.gtimg.cn/appstock/app/minute/query', {'code': symbol})
    content = value['data'][symbol]
    data = content['data']
    actual = datetime.strptime(data['date'], '%Y%m%d').date().isoformat()
    if actual != day:
        raise ValueError('Minute data belongs to a different trading date')
    prev = number(content['qt'][symbol][4])
    points = []
    cumulative = []
    for line in data['data']:
        fields = line.split()
        price = number(fields[1])
        hhmm = fields[0][:2] + ':' + fields[0][2:]
        points.append({'time': hhmm, 'price': price, 'change_percent': (price / prev - 1)*100})
        cumulative.append((hhmm, number(fields[3])))
    if not points:
        raise ValueError('Empty minute series')
    return {'date': actual, 'code': code, 'line': points, 'cumulative': cumulative, **provenance('tencent')}


async def eastmoney_minute(code, day):
    market = 1 if cn_symbol(code).startswith('sh') else 0
    value = await get('https://push2.eastmoney.com/api/qt/stock/trends2/get', {
        'secid': f'{market}.{code}', 'ndays': 1, 'iscr': 0,
        'fields1': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58'}, ttl=60)
    data = value['data']
    if value.get('rc') != 0 or data.get('code') != code:
        raise ValueError('Incorrect minute instrument')
    previous = number(data['preClose'])
    points, cumulative, amount = [], [], 0.0
    for row in data['trends']:
        fields = row.split(',')
        if fields[0][:10] != day:
            raise ValueError('Minute data belongs to a different trading date')
        hhmm, price = fields[0][11:16], number(fields[2])
        amount += number(fields[6])
        points.append({'time': hhmm, 'price': price, 'change_percent': (price/previous-1)*100})
        cumulative.append((hhmm, amount))
    if not points:
        raise ValueError('Empty minute series')
    return {'date': day, 'code': code, 'line': points, 'cumulative': cumulative, **provenance('eastmoney')}


async def minute(code, day):
    for provider in (eastmoney_minute, tencent_minute):
        try:
            return await provider(code, day)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            if provider is tencent_minute:
                raise


async def stock_line(code, day):
    try:
        return await minute(code, day)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        symbol = cn_symbol(code)
        value = await get('https://ifzq.gtimg.cn/appstock/app/kline/mkline',
                          {'param': f'{symbol},m5,,320'}, ttl=60)
        data = value['data'][symbol]
        rows = [r for r in data['m5'] if r[0][:8] == day.replace('-', '')]
        if not rows:
            raise ValueError('No five-minute prices for requested trading date')
        # Derive the correct previous close even for historical intraday bars.
        bars = await daily_bars(symbol)
        index = next((i for i,r in enumerate(bars) if r[0] == day), 0)
        if index < 1:
            raise ValueError('Missing historical previous close')
        previous = number(bars[index-1][2])
        return {'date': day, 'code': code, 'interval': '5m', 'line': [
            {'time': r[0][8:10]+':'+r[0][10:12], 'price': number(r[2]),
             'change_percent': (number(r[2])/previous-1)*100} for r in rows], **provenance('tencent')}


async def etf_snapshot(day):
    symbols = [cn_symbol(c) for c in ETF_CODES]
    raw = await get('https://qt.gtimg.cn/q=' + ','.join(symbols), raw=True, ttl=60)
    amounts, timestamps = {}, []
    for line in raw.decode('gb18030').split(';'):
        if '="' not in line:
            continue
        key, value = line.strip().split('="', 1)
        fields = value.rstrip('"').split('~')
        symbol = key.removeprefix('v_')
        if symbol not in symbols or len(fields) <= 35:
            continue
        stamp = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=CN)
        if stamp.date().isoformat() != day:
            raise ValueError('ETF snapshot belongs to another date')
        amounts[symbol] = number(fields[35].split('/')[2])
        timestamps.append(stamp.isoformat())
    if set(amounts) != set(symbols):
        raise ValueError('Incomplete ETF snapshot')
    return {'date': day, 'status': 'snapshot', 'updated_at': min(timestamps),
            'amount': sum(amounts.values())/1e8, 'minutes': [], 'windows': [], 'peak_window': None,
            'errors': {'minutes': 'unavailable', 'baseline': 'unavailable'},
            **provenance('tencent', method='etf_snapshot')}


async def etf():
    day = (await trading_dates())[0]
    series = await asyncio.gather(*(minute(code, day) for code in ETF_CODES), return_exceptions=True)
    if any(isinstance(item, Exception) for item in series):
        return await etf_snapshot(day)
    # Use only the common timestamp prefix. Different update speeds must not
    # produce a false spike by treating an absent fund as zero.
    maps = [dict(s['cumulative']) for s in series]
    common = sorted(h for h in set.intersection(*(set(m) for m in maps)) if '09:30' <= h <= '11:30' or '13:00' <= h <= '15:00')
    if not common:
        raise ValueError('ETF minute series do not overlap')
    minutes, prior = [], 0.0
    totals = {}
    for hhmm in common:
        total = sum(m[hhmm] for m in maps)
        if total < prior:
            raise ValueError('Invalid cumulative turnover')
        minutes.append([hhmm, (total-prior)/1e8])
        totals[hhmm] = total
        prior = total
    bounds = [('09:30','10:00'),('10:00','10:30'),('10:30','11:00'),('11:00','11:30'),
              ('13:00','13:30'),('13:30','14:00'),('14:00','14:30'),('14:30','15:00')]
    windows, base = [], 0.0
    for start, end in bounds:
        if end not in totals:
            break
        end_amount = totals[end]
        windows.append({'start': start, 'end': end, 'amount': (end_amount-base)/1e8, 'ratio': None})
        base = end_amount
    # Historical 20-day same-window turnover is not present in this source.
    # Do not synthesize it from price * volume or label a volume ratio as money.
    return {'date': day, 'status': 'closed' if common[-1] == '15:00' else 'trading',
            'updated_at': f'{day}T{common[-1]}:00+08:00', 'amount': prior/1e8, 'minutes': minutes,
            'peak_window': None, 'windows': windows, 'errors': {'baseline': 'unavailable'},
            **provenance(*sorted({provider['id'] for item in series for provider in item.get('sources', [PROVIDERS['tencent']])}), method='etf_turnover')}


def parse_cffex(content, day, product):
    long = short = long_change = short_change = 0
    contracts = set()
    for row in csv.reader(io.StringIO(content.decode('gb18030'))):
        if len(row) < 12 or not row[0].strip().isdigit():
            continue
        if row[0].strip() != day.replace('-', '') or not row[1].startswith(product):
            raise ValueError('CFFEX file has a different trading date or product')
        if row[2].strip().isdigit() and 1 <= int(row[2]) <= 20:
            contracts.add(row[1])
            if row[6].replace('（','(').strip() == '中信期货(代客)':
                long += int(row[7]); long_change += int(row[8])
            if row[9].replace('（','(').strip() == '中信期货(代客)':
                short += int(row[10]); short_change += int(row[11])
    if not contracts:
        raise ValueError('Empty CFFEX rankings')
    return {'long': long, 'short': short, 'net': long-short, 'net_change': long_change-short_change}


async def futures_day(day):
    async def product(name):
        # CFFEX publishes these files over HTTP; its HTTPS endpoint is unavailable.
        content = await get(f'http://www.cffex.com.cn/sj/ccpm/{day[:7].replace("-", "")}/{day[8:]}/{name}_1.csv',
                            ttl=300 if day == now().date().isoformat() else 86400, raw=True)
        return parse_cffex(content, day, name)
    values = await asyncio.gather(*(product(name) for name in ('IF','IH','IC','IM')))
    return {k: sum(v[k] for v in values) for k in ('long','short','net','net_change')}


async def futures(dates):
    values = await asyncio.gather(*(futures_day(d) for d in dates[:10]), return_exceptions=True)
    valid = [(d, v) for d, v in zip(dates, values) if isinstance(v, dict)]
    if not valid:
        raise ValueError('No published CFFEX rankings')
    day, total = valid[0]
    return {'date': day, 'updated_at': now().isoformat(), 'member': '中信期货（代客）', 'total': total,
            'series': [{'date': d, **v} for d, v in reversed(valid)], 'partial': len(valid) != len(values),
            **provenance('cffex', method='cffex_top20')}


async def report(name, column, day):
    value = await get('https://datacenter-web.eastmoney.com/api/data/v1/get', {
        'reportName': name, 'columns': 'ALL', 'pageSize': 5000, 'pageNumber': 1,
        'filter': f"({column}='{day}')"}, ttl=300)
    result = value.get('result')
    if not isinstance(result, dict) or result.get('pages', 1) > 1:
        raise ValueError('Missing or truncated disclosure')
    rows = result['data']
    if len(rows) != result.get('count') or any(r[column][:10] != day for r in rows):
        raise ValueError('Incomplete or misdated disclosure')
    return rows


def single_day_rows(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['SECURITY_CODE'], []).append(row)
    # Multiple listing reasons repeat a stock's amounts. Prefer one single-day
    # reason and take one row per stock; never add duplicate reasons together.
    return [next((r for r in group if '三' not in r.get('EXPLANATION','') and '3' not in r.get('EXPLANATION','')), group[0]) for group in grouped.values()]


async def lhb(dates):
    for day in dates[:3]:
        try:
            seats, stocks, institutions = await asyncio.gather(
                report('RPT_OPERATEDEPT_ACTIVE','ONLIST_DATE',day),
                report('RPT_DAILYBILLBOARD_DETAILSNEW','TRADE_DATE',day),
                report('RPT_ORGANIZATION_TRADE_DETAILS','TRADE_DATE',day))
            if not stocks:
                continue
            break
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            if day == dates[min(2,len(dates)-1)]:
                raise
    else:
        raise ValueError('No published LHB disclosure')
    output = []
    for row in sorted(seats, key=lambda r: number(r['TOTAL_NETAMT']), reverse=True)[:6]:
        names = (row.get('SECURITY_NAME_ABBR') or '').split()
        codes = (row.get('BUY_STOCK') or '').split()
        output.append({'key': row['OPERATEDEPT_CODE'], 'alias': row['OPERATEDEPT_NAME'],
                       'net': number(row['TOTAL_NETAMT']),
                       'stocks': [{'code': c.split('.')[0], 'name': n} for c,n in zip(codes,names)]})
    return {'available': True, 'date': day, 'observed_at': now().isoformat(), 'seats': output,
            'count': len({r['SECURITY_CODE'] for r in stocks}),
            'institution_net': sum(number(r['NET_BUY_AMT']) for r in single_day_rows(institutions)),
            'connect_net': sum(number(r['TOTAL_NETAMT']) for r in seats if r['OPERATEDEPT_NAME'] in ('沪股通专用','深股通专用')),
            **provenance('eastmoney', method='lhb_disclosure')}


async def calendar():
    day = now().date().isoformat()
    value = await get('https://finance.pae.baidu.com/sapi/v1/financecalendar', {
        'start_date': day, 'end_date': day, 'pn': 0, 'rn': 100, 'cate': 'economic_data', 'finClientType': 'pc'}, ttl=1800)
    groups = value['Result']['calendarInfo']
    group = next(r for r in groups if r['date'] == day)
    rows = list(group['list'])
    for page in range(1, (int(group['total'])+99)//100):
        if page > 9:
            raise ValueError('Calendar pagination exceeds limit')
        result = await get('https://finance.pae.baidu.com/sapi/v1/financecalendar', {
            'start_date': day, 'end_date': day, 'pn': page, 'rn': 100, 'cate': 'economic_data', 'finClientType': 'pc'}, ttl=1800)
        rows.extend(next(r for r in result['Result']['calendarInfo'] if r['date'] == day)['list'])
    events = [r for r in rows if int(r.get('star') or 0) >= 2]
    return {'macro': [{k: r[k] for k in ('date','time','title')} for r in events], **provenance('baidu', method='calendar_stars')}


async def daily():
    dates = await trading_dates()
    values = await asyncio.gather(lhb(dates), futures(dates), calendar(), return_exceptions=True)
    result, errors = {}, {}
    for key, value in zip(('lhb','futures','calendar'), values):
        result[key] = None if isinstance(value, Exception) else value
        if isinstance(value, Exception):
            errors[key] = 'unavailable'
    if all(v is None for v in result.values()):
        raise ValueError('No daily resources available')
    return {**result, 'errors': errors, **provenance('eastmoney','cffex','baidu')}


def parse_quotes(content):
    output = {}
    for line in content.decode('gb18030').split(';'):
        if '="' not in line:
            continue
        key, value = line.strip().split('="', 1)
        fields = value.rstrip('"').split('~')
        if len(fields) < 33:
            continue
        try:
            output[key.removeprefix('v_')] = {'price': number(fields[3]), 'change_percent': number(fields[32]),
                 'quote_at': datetime.strptime(fields[30], '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY).isoformat()}
        except (ValueError, TypeError):
            continue
    return output


async def commodity(symbol, identifier, name):
    value = await get(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}', {'interval': '1d', 'range': '5d'}, ttl=60)
    result = value['chart']['result'][0]
    meta = result['meta']
    price = number(meta['regularMarketPrice'])
    change = optional(meta.get('regularMarketChangePercent'))
    if change is None:
        # chartPreviousClose is the start of range, NOT necessarily yesterday.
        closes = [v for v in result['indicators']['quote'][0]['close'] if v is not None]
        change = (price / number(closes[-2])-1)*100 if len(closes) >= 2 else None
    return {'symbol': identifier, 'name': name, 'price': price, 'change_percent': change,
            'quote_at': datetime.fromtimestamp(meta['regularMarketTime'], CN).isoformat(),
            'url': f'https://finance.yahoo.com/quote/{symbol}/'}


async def overseas():
    symbols = ['usDJI','usIXIC','usINX'] + ['us'+s for s,_ in SECTORS]
    raw, *commodities = await asyncio.gather(
        get('https://qt.gtimg.cn/q=' + ','.join(symbols), raw=True),
        commodity('BZ=F','BRENT','布伦特原油期货'), commodity('GC=F','XAU','黄金期货'), commodity('SI=F','XAG','白银期货'),
        return_exceptions=True)
    quotes = {} if isinstance(raw, Exception) else parse_quotes(raw)
    if not quotes and all(isinstance(c, Exception) for c in commodities):
        raise ValueError('No overseas quotes')
    sectors = [{'id': symbol, 'name': name, 'symbol': symbol, 'regular': {'change_percent': quotes.get('us'+symbol,{}).get('change_percent')},
                'quote_at': quotes.get('us'+symbol,{}).get('quote_at'), 'url': f'https://finance.yahoo.com/quote/{symbol}/'} for symbol,name in SECTORS]
    indices = [{'symbol': s, 'name': n, **quotes.get(s, {'price': None, 'change_percent': None}),
                'url': f'https://gu.qq.com/{s}'} for s,n in [('usDJI','道琼斯'),('usIXIC','纳斯达克'),('usINX','标普500')]]
    errors = {} if len(quotes) == len(symbols) and all(isinstance(c,dict) for c in commodities) else {'quotes': 'partial'}
    return {'industry': {'meta': {'generated_at': max((q['quote_at'] for q in quotes.values()), default=None), 'stale': False},
                         'sectors': sectors},
            'indicators': {'commodities': {'items': [c for c in commodities if isinstance(c,dict)]}, 'groups': [{'title': '美股指数', 'items': indices}]},
            'errors': errors, **provenance('tencent','yahoo', method='sector_etfs')}


async def fetch(resource, date=None):
    if resource.startswith('minute/'):
        return await stock_line(resource.split('/')[1], date)
    return await {'board': lambda: board(date), 'dates': trading_dates, 'daily': daily, 'etf': etf, 'overseas': overseas}[resource]()
