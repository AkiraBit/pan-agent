from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from marketdata import MarketData, SourceConfig, StaticConfigProvider, Symbol
from marketdata.vendors.longbridge import (
    LongbridgeCapitalFlowVendor, LongbridgeDividendVendor, LongbridgeEventsVendor,
    LongbridgeFundamentalsVendor, LongbridgeNewsVendor, symbol,
)


def test_symbols_quotes_and_kline_use_injected_transport():
    assert [symbol(Symbol.parse(c)) for c in ['510300', '159919', '00700', 'AAPL']] == [
        '510300.SH', '159919.SZ', '700.HK', 'AAPL.US']
    with pytest.raises(ValueError): symbol(Symbol.parse('920001'))
    def query(tool, args):
        if tool == 'quote':
            return [{'symbol': args['symbols'][0], 'last_done': '4', 'prev_close': '5',
                     'timestamp': '2026-11-13T15:00:00+08:00', 'turnover': '100000000', 'volume': '30'}]
        assert args['count'] == 30 and args['forward_adjust'] is True
        return [{'timestamp': '2026-11-13T00:00:00+08:00', 'open': '5', 'close': '4', 'high': '5', 'low': '4',
                 'volume': '30', 'turnover': '100000000'}]
    md = MarketData(StaticConfigProvider({k: [SourceConfig(vendor='longbridge')] for k in ['quote', 'kline']}), longbridge_transport=query)
    quote = md.quotes(['510300'])[0]
    assert quote.current_price == 4 and quote.change_pct == pytest.approx(-20)
    assert quote.turnover == 100000000 and quote.source == 'longbridge'
    assert quote.quote_date.isoformat() == '2026-11-13'
    bar = md.klines('510300', market='CN', days=30)[0]
    assert bar.turnover == quote.turnover and bar.close == quote.current_price


def test_money_flow_does_not_invent_main_or_super_large_buckets():
    query = Mock(return_value={'capital_in': {'large': '30', 'medium': '8'},
                               'capital_out': {'large': '10', 'medium': '12'}, 'data_available': True})
    row = LongbridgeCapitalFlowVendor(query).fetch([Symbol.parse('600519')], {})[0]
    assert row.big_net_inflow == 20 and row.mid_net_inflow == -4
    assert row.main_net_inflow is None and row.super_net_inflow is None and row.small_net_inflow is None
    assert row.measurement == 'longbridge_order_size'


def test_fundamentals_units_unknown_fields_and_financial_report():
    def query(tool, args):
        return {'static_info': [{'symbol': 'AAPL.US', 'name_en': 'Apple', 'currency': 'USD', 'eps': '2.1'}],
                'calc_indexes': [{'symbol': 'AAPL.US', 'total_market_value': '1000000000', 'pe_ttm_ratio': '20'}],
                'financial_report_snapshot': {'fiscal_year': 2026, 'ticker': 'AAPL', 'fp_end': '2026.09.26',
                    'fr_revenue': {'value': '100000000', 'yoy': '10'}, 'fr_profit': {'value': '20000000'},
                    'fr_roe_ttm': '15'}}[tool]
    row = LongbridgeFundamentalsVendor(query).fetch([Symbol.parse('AAPL')], {})[0]
    assert row.total_market_value == 10 and row.pb is None and row.currency == 'USD'
    assert row.report_date == '2026-09-26' and row.revenue == 100000000 and row.roe == 15


def test_news_original_citations_filing_dates_and_dividend_prose():
    at = datetime.now(timezone.utc).isoformat()
    news = LongbridgeNewsVendor(lambda *a: [{'id': '1', 'title': 'News', 'description': 'Summary',
        'published_at': at, 'url': 'https://longbridge.cn/news/1', 'source_url': 'https://example.com/original'}])
    assert news.fetch([Symbol.parse('AAPL')], {})[0].url == 'https://example.com/original'
    events = LongbridgeEventsVendor(lambda *a: [{'id': '2', 'title': '10-K', 'publish_at': at,
                                               'file_urls': ['https://www.sec.gov/example']}])
    assert events.fetch([Symbol.parse('AAPL')], {})[0].event_type == 'announcement'
    dividends = LongbridgeDividendVendor(lambda *a: {'list': [{'ex_date': '2026.11.12', 'desc': '每股派息 0.27 USD'}]})
    row = dividends.fetch([Symbol.parse('AAPL')], {})[0]
    assert row.ex_date == '2026-11-12' and row.dividend_per_share is None
    assert row.description == '每股派息 0.27 USD'
