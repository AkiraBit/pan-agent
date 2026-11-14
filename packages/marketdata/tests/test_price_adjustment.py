"""Synthetic provider responses; live source checks are separate acceptance."""
from copy import deepcopy
import json
import pytest
import marketdata.price_adjustment as pa

CODE = 'sh688801'
ROWS = [['2026-11-11', '20', '20', '21', '19', '100'], ['2026-11-12', '10', '10', '11', '9', '200'], ['2026-11-13', '11', '11', '12', '10', '300']]
FACTORS = [{'d':'1900-01-01','f':'2'}, {'d':'2026-11-12','f':'1'}]


def response(rows=ROWS, key='day', code=CODE):
    return {'code':0,'data':{code:{key:deepcopy(rows)}}}


def factors(rows=FACTORS, code=CODE, total=None):
    return 'var '+code+'qfq='+json.dumps({'total':len(rows) if total is None else total,'data':rows})+'\n/* provider comment */'


def source(monkeypatch, first=None, raw=None, factor=None):
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs.get('params')))
        if 'qfq.js' in url:return factor if factor is not None else factors()
        return first if kwargs['params']['param'].endswith('qfq') else raw or response()
    monkeypatch.setattr(pa,'market_get',get)
    return calls


def test_explicit_qfq_field_uses_one_request_and_archives_response(monkeypatch):
    calls=source(monkeypatch,first=response(key='qfqday'))
    result=pa.adjusted_daily_series('688801.SH')
    assert result['adjustment']=='qfq' and result['price_basis']['method']=='tencent_qfq_field'
    assert result['rows'][0]['close']==20 and len(calls)==1
    assert result['price_basis']['response_hash']==pa.fingerprint(result['raw']['qfq_request']['response'])


def test_ambiguous_day_is_replaced_by_explicit_raw_request_and_dated_factors(monkeypatch):
    # The first response could already be adjusted: do not adjust it twice.
    initial=deepcopy(ROWS);initial[0][1:5]=['10','10','10.5','9.5']
    calls=source(monkeypatch,first=response(initial))
    result=pa.adjusted_daily_series('688801.SH')
    assert result['adjustment']=='qfq' and result['source']=='tencent+sina'
    assert [r['close'] for r in result['rows']]==[10,10,11]
    assert calls[1][1]['param'].endswith(',')
    basis=result['price_basis'];assert basis['inputs'][0]=={'date':'2026-11-11','factor_date':'1900-01-01','factor':'2','raw_close':20,'adjusted_close':10}
    assert result['raw']['unadjusted_request']['response']['data'][CODE]['day'][0][2]=='20'
    assert len(basis['factor_response_hash'])==64


@pytest.mark.parametrize('text', [
    '', factors(code='sh600825'), factors(total=99), factors(rows=[]),
    factors([{'d':'2026-11-12','f':'1'}]),
    factors([{'d':'1900-01-01','f':'0'}]), factors([{'d':'1900-01-01','f':'NaN'}]),
    factors([{'d':'1900-01-01','f':'1'},{'d':'1900-01-01','f':'1'}]),
    factors([{'d':'2099-01-01','f':'1'}]), factors()+';doSomething()',
])
def test_incomplete_wrong_subject_or_invalid_factors_cannot_clear_gap(monkeypatch,text):
    source(monkeypatch,first=response(),factor=text)
    result=pa.adjusted_daily_series('688801.SH')
    assert result['adjustment']=='unverified' and result['status']=='unavailable' and not result['rows']


@pytest.mark.parametrize('rows', [ROWS[::-1], ROWS+[ROWS[-1]], [ROWS[0],['2099-01-01','1','1','1','1','1']], [['2026-11-13','1','NaN','2','1','1']]])
def test_malformed_history_is_not_silently_filtered(monkeypatch,rows):
    calls=source(monkeypatch,first=response(rows,key='qfqday'))
    result=pa.adjusted_daily_series('688801.SH')
    assert result['status']=='unavailable' and not result['rows'] and len(calls)==1


def test_raw_date_mismatch_is_not_a_valid_adjustment_basis(monkeypatch):
    source(monkeypatch,first=response(),raw=response(ROWS[:-1]))
    assert pa.adjusted_daily_series('688801.SH')['reason']=='raw_history_dates_mismatch'


def test_index_does_not_fetch_stock_factors_and_unknown_symbol_fails(monkeypatch):
    calls=source(monkeypatch,first=response(code='sh000688'))
    result=pa.adjusted_daily_series('sh000688')
    assert result['adjustment']=='index_unadjusted' and len(calls)==1
    assert pa.adjusted_daily_series('invalid')['status']=='invalid_symbol'


def test_no_factor_changes_still_require_and_archive_explicit_basis(monkeypatch):
    source(monkeypatch,first=response(),factor=factors([{'d':'1900-01-01','f':'1'},{'d':'2026-09-11','f':'1'}]))
    result=pa.adjusted_daily_series('688801.SH')
    assert result['rows'][0]['close']==20 and result['price_basis']['factor_count']==2
    assert len(result['price_basis']['inputs'])==3
