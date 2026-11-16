import pytest

from test_etf_dashboard import anyio_backend, board, database  # noqa: F401
from src.modules.market.etf import free_sources, free_store, history, service


def save(code, prices):
    rows = [{'code': code, 'date': day, 'close': close} for day, close in prices.items()]
    free_store.save(free_sources.Batch('price', 'tencent', rows, {}, free_sources.PRICE, {'code': code}),
                    f'price:tencent:{code}:test')


def test_market_comparison_uses_one_baseline_gaps_and_vintages(database, board, monkeypatch):
    first, middle, last = '2026-11-11', '2026-11-12', '2026-11-13'
    cutoff = '2026-11-14T00:00:00+00:00'
    monkeypatch.setattr(service, 'timestamp', lambda: cutoff)
    service.save_board(board, board)
    save('000001', {first: 3100, middle: 3000, last: 3300})
    save('000300', {first: 4200, middle: 4000, last: 3800})
    save('000688', {middle: 600})

    def read(start=first, vintage=None):
        return history.read_history(start, last, [first, middle, last], cutoff=vintage)

    original = read()
    assert original['benchmark_base_date'] == middle
    assert [point['date'] for point in original['series']] == [first, middle, last]
    assert original['series'][0]['benchmarks']['000001']['return_percent'] is None
    assert {point['return_percent'] for point in original['series'][1]['benchmarks'].values()} == {0}
    assert original['series'][2]['benchmarks']['000001']['return_percent'] == pytest.approx(10)
    assert original['series'][2]['benchmarks']['000300']['return_percent'] == pytest.approx(-5)
    assert '000688' not in original['series'][2]['benchmarks']
    assert original['series'][2]['net'] == 4
    assert original['series'][2]['amount'] == 10
    assert read(last)['benchmark_base_date'] is None

    monkeypatch.setattr(service, 'timestamp', lambda: '2026-11-15T00:00:00+00:00')
    save('000688', {middle: 625, last: 750})
    revised = read()
    assert revised['series'][2]['benchmarks']['000688']['return_percent'] == pytest.approx(20)
    assert read(last)['benchmark_base_date'] == last
    assert read(vintage=cutoff)['series'] == original['series']


@pytest.mark.anyio
@pytest.mark.parametrize('code', free_sources.BENCHMARK_CODES)
async def test_index_fetch_uses_explicit_shanghai_symbols(code):
    class Client:
        async def json(self, url, params):
            assert url == free_sources.PRICE
            symbol = f'sh{code}'
            assert params['param'] == f'{symbol},day,2026-11-13,2026-11-13,640,'
            return {'code': 0, 'data': {symbol: {'day': [['2026-11-13', '900', '1000', '1100', '890', '10000']]}}}

    batch = await free_sources.prices(Client(), code, '2026-11-13', '2026-11-13')
    assert [(row['code'], row['close']) for row in batch.rows] == [(code, 1000)]


def test_market_history_groups_only_observed_funds_by_index(database, board):
    etf = board['etfs'][0]
    board['etfs'] += [
        {**etf, 'code': '510310', 'net': -1},
        {**etf, 'code': '510330', 'net': None},
        {**etf, 'code': '588000', 'index': '科创50', 'net': -4},
    ]
    board.update(net=-1, covered=3)
    service.save_board(board, board)
    result = history.read_history('2026-11-12', board['date'], [board['date'], '2026-11-12'])
    previous, current = result['series']
    assert previous['net_by_index']['沪深300'] == {'net': None, 'covered': 0, 'expected': 3}
    assert current['net_by_index'] == {
        '沪深300': {'net': 3, 'covered': 2, 'expected': 3},
        '科创50': {'net': -4, 'covered': 1, 'expected': 1},
    }
    assert current['net'] == -1
    filtered = history.read_history(board['date'], board['date'], [board['date']], code='588000')
    assert filtered['series'][0]['net_by_index'] == {'科创50': {'net': -4, 'covered': 1, 'expected': 1}}
