"""Longbridge public market data; OAuth/HTTP is injected by the host.

No credentials, database or PanWatch imports belong in this standalone package.
Missing provider fields remain unknown, including unsupported money-flow buckets.
"""
from datetime import date, datetime, timedelta, timezone
import math

from marketdata.symbol import Market, Symbol
from marketdata.types import Bar, CapitalFlow, DividendItem, EventItem, Fundamentals, NewsArticle, Quote


def symbol(value: Symbol) -> str:
    if value.market == Market.HK:
        return f'{int(value.code)}.HK' if value.code.isdigit() else value.code + '.HK'
    if value.market == Market.US:
        return value.code.upper() + '.US'
    exchange = value.to_tencent()[:2].upper()
    if exchange not in {'SH', 'SZ'}:
        raise ValueError('Longbridge does not support this mainland exchange')
    return value.code + '.' + exchange


def number(value):
    if value in (None, '', '--'):
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean measurement')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite measurement')
    return result


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Missing source timezone')
    return result


def calendar_date(value):
    return date.fromisoformat(value[:10].replace('.', '-')).isoformat() if value else None


class LongbridgeVendor:
    name = 'longbridge'
    supports_markets = {'CN', 'HK', 'US'}

    def __init__(self, transport=None):
        self.transport = transport

    def call(self, tool, arguments):
        if self.transport is None:
            raise RuntimeError('Longbridge connection is not configured')
        return self.transport(tool, arguments)


class LongbridgeQuoteVendor(LongbridgeVendor):
    def fetch(self, symbols, config):
        requested = {symbol(s): s for s in symbols}
        rows = self.call('quote', {'symbols': list(requested)})
        result = []
        for row in rows:
            s = requested.get(row.get('symbol'))
            price = number(row.get('last_done'))
            if s is None or price is None or price <= 0:
                continue
            previous, at = number(row.get('prev_close')), stamp(row['timestamp'])
            result.append(Quote(symbol=s.code, market=s.market.value, current_price=price,
                prev_close=previous, open_price=number(row.get('open')), high_price=number(row.get('high')),
                low_price=number(row.get('low')), volume=number(row.get('volume')), turnover=number(row.get('turnover')),
                change_amount=price - previous if previous is not None else None,
                change_pct=(price / previous - 1) * 100 if previous else None,
                timestamp=datetime.now(timezone.utc), quote_date=at.date(), source_timestamp=at, source=self.name))
        return result


class LongbridgeKlineVendor(LongbridgeVendor):
    def fetch(self, symbols, config):
        if not symbols:
            return []
        rows = self.call('candlesticks', {'symbol': symbol(symbols[0]), 'period': 'day',
            'count': min(max(int(config.get('days', 120)), 1), 1000), 'forward_adjust': True, 'trade_sessions': 'intraday'})
        result = []
        seen = set()
        for row in rows:
            day = stamp(row['timestamp']).date().isoformat()
            values = {key: number(row.get(key)) for key in ('open', 'close', 'high', 'low')}
            if any(v is None or v <= 0 for v in values.values()) or day in seen:
                raise ValueError('Invalid or duplicate daily bar')
            seen.add(day)
            result.append(Bar(date=day, **values, volume=number(row.get('volume')) or 0,
                              turnover=number(row.get('turnover')), source=self.name))
        return sorted(result, key=lambda r: r.date)


class LongbridgeCapitalFlowVendor(LongbridgeVendor):
    def fetch(self, symbols, config):
        result = []
        for s in symbols:
            row = self.call('capital_distribution', {'symbol': symbol(s)})
            if row.get('data_available') is False:
                continue
            incoming, outgoing = row.get('capital_in') or {}, row.get('capital_out') or {}
            def net(bucket):
                a, b = number(incoming.get(bucket)), number(outgoing.get(bucket))
                return a - b if a is not None and b is not None else None
            values = [net(k) for k in ('large', 'medium', 'small')]
            if any(v is not None for v in values):
                # Longbridge large/medium/small is not Eastmoney's main/super-large definition.
                result.append(CapitalFlow(symbol=s.code, name='', big_net_inflow=values[0],
                    mid_net_inflow=values[1], small_net_inflow=values[2], source=self.name,
                    measurement='longbridge_order_size', source_timestamp=row.get('timestamp'),
                    currency={'CN': 'CNY', 'HK': 'HKD', 'US': 'USD'}[s.market.value]))
        return result


class LongbridgeFundamentalsVendor(LongbridgeVendor):
    def fetch(self, symbols, config):
        requested = {symbol(s): s for s in symbols}
        static = self.call('static_info', {'symbols': list(requested)})
        indexes = self.call('calc_indexes', {'symbols': list(requested),
            'indexes': ['PeTtmRatio', 'PbRatio', 'DividendRatioTtm', 'TotalMarketValue']})
        indexed = {r['symbol']: r for r in indexes}
        result = []
        for row in static:
            s = requested.get(row.get('symbol'))
            if s is None or not row.get('name_cn', row.get('name_en')):
                continue
            value = indexed.get(row['symbol'], {})
            cap = number(value.get('total_market_value'))
            fundamental = Fundamentals(symbol=s.code, market=s.market.value,
                name=row.get('name_cn') or row.get('name_en', ''), pe_ttm=number(value.get('pe_ttm_ratio')),
                pb=number(value.get('pb_ratio')), dividend_yield=number(value.get('dividend_ratio_ttm')),
                total_market_value=cap / 1e8 if cap is not None else None,
                total_shares=number(row.get('total_shares')), float_shares=number(row.get('circulating_shares')),
                eps=number(row.get('eps')), bps=number(row.get('bps')), source=self.name, currency=row.get('currency', ''))
            if s.market in {Market.HK, Market.US}:
                try:
                    report = self.call('financial_report_snapshot', {'symbol': symbol(s)})
                except RuntimeError:
                    report = {}  # Valuations remain usable when no financial report is available.
                if report.get('fiscal_year') and str(report.get('ticker', '')).lstrip('0') == s.code.lstrip('0'):
                    revenue, profit = report.get('fr_revenue') or {}, report.get('fr_profit') or {}
                    fundamental.report_date = calendar_date(report.get('fp_end')) or ''
                    fundamental.revenue = number(revenue.get('value'))
                    fundamental.revenue_yoy = number(revenue.get('yoy'))
                    fundamental.net_profit = number(profit.get('value'))
                    fundamental.net_profit_yoy = number(profit.get('yoy'))
                    fundamental.roe = number(report.get('fr_roe_ttm'))
                    fundamental.net_margin = number(report.get('fr_profit_margin'))
            result.append(fundamental)
        return result


class LongbridgeNewsVendor(LongbridgeVendor):
    def fetch(self, symbols, config):
        result = []
        for s in symbols:
            rows = self.call('news', {'symbol': symbol(s), 'count': 50})
            for row in rows:
                if row.get('title') and row.get('published_at'):
                    result.append(NewsArticle(source=self.name, external_id=str(row['id']), title=row['title'],
                        content=row.get('description') or '', publish_time=stamp(row['published_at']),
                        symbols=[s.code], url=row.get('source_url') or row.get('url') or ''))
        return result


class LongbridgeEventsVendor(LongbridgeVendor):
    supports_markets = {'HK', 'US'}

    def fetch(self, symbols, config):
        result = []
        since = datetime.now(timezone.utc) - timedelta(days=int(config.get('since_days', 7)))
        for s in symbols:
            for row in self.call('filings', {'symbol': symbol(s)}):
                at = stamp(row['publish_at'])
                if at >= since and row.get('title'):
                    result.append(EventItem(source=self.name, external_id=str(row['id']), event_type='announcement',
                        title=row['title'], publish_time=at, symbols=[s.code], importance=0,
                        url=next(iter(row.get('file_urls') or []), '')))
        return result


class LongbridgeDividendVendor(LongbridgeVendor):
    supports_markets = {'HK', 'US'}

    def fetch(self, symbols, config):
        result = []
        for s in symbols:
            data = self.call('dividend', {'symbol': symbol(s)})
            for row in data.get('list', []):
                if row.get('ex_date'):
                    # Amount is prose, often with a foreign currency or per-lot basis.
                    # Preserve the description instead of fabricating a per-share amount.
                    result.append(DividendItem(ex_date=calendar_date(row['ex_date']), symbol=s.code,
                        description=row.get('desc') or '', record_date=calendar_date(row.get('record_date')),
                        payment_date=calendar_date(row.get('payment_date')), source=self.name))
        return result
