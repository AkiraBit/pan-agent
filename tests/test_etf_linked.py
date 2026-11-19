import asyncio
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.modules.market.etf import intraday, linked
from src.modules.market.etf.models import EtfAnalysisCache, EtfAnalysisMinute
from src.modules.market.api.etf import router
from src.platform.persistence.database import Base

DAY = date(2026, 11, 19)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'linked.db'}")
    Base.metadata.create_all(engine, tables=[EtfAnalysisCache.__table__, EtfAnalysisMinute.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(linked, 'SessionLocal', sessions)
    monkeypatch.setattr(intraday, 'now_cn', lambda: datetime(2026, 11, 19, 16, tzinfo=intraday.CN))
    yield sessions
    engine.dispose()


def test_snapshot_uses_dated_latest_valid_quotes_and_separates_boards(storage):
    def row(code, close, stamp='09:31:02', vol=1):
        return dict(ts_code=code, close=close, pre_close=10, vol=vol, trade_time=f'{DAY} {stamp}')
    rows = [row('600000.SH', 11), row('000001.SZ', 9), row('300001.SZ', 12), row('688001.SH', 8), row('920001.BJ', 10),
            row('600000.SH', 10, '09:31:01'), row('600000.SH', 20, '09:32:01'), row('600001.SH', 15, vol=0),
            {**row('600002.SH', 15), 'trade_time':'2026-11-18 09:31:00'}]
    linked.capture_observation(DAY, '09:31', rows)
    result = linked.observations(DAY, '09:31')['09:31']
    assert result['boards']['all'] == dict(up=2, down=2, flat=1, total=5, median=0)
    assert result['boards']['growth']['up'] == 1
    assert result['boards']['star']['down'] == 1
    assert result['boards']['beijing']['flat'] == 1
    assert result['returns']['600000.SH'] == .1
    assert linked.observations(DAY, '09:30') == {}


def test_reconstructed_minutes_preserve_gaps_and_never_replace_captured_observations(storage):
    linked.save_observation(DAY, '09:30', {'600000.SH': .25})
    linked.save_reconstructed(DAY, {'600000.SH':10}, {'600000.SH':{'09:30':10,'09:31':None,'09:33':11}},
                              ('09:30','09:31','09:32','09:33'), complete=False)
    recorded = linked.observations(DAY, '15:00')
    assert recorded['09:30']['returns']['600000.SH'] == .25
    assert recorded['09:31']['returns']['600000.SH'] == 0
    assert '09:32' not in recorded
    assert recorded['09:33']['returns']['600000.SH'] == .1
    assert 'boards' not in recorded['09:33']


def test_component_coverage_is_explicit_and_dated_basket_is_reused(storage, monkeypatch):
    calls=[]
    async def request(op, params, fields=''):
        calls.append(op)
        if op == 'etf_sh_cons':
            return [dict(ts_code='510300.SH',trade_date='20261119',con_code=code,con_name=name,qty=0 if code == '300001.SZ' else 1)
                    for code,name in [('600000.SH','A'),('000001.SZ','B'),('300001.SZ','C')]]
        return [dict(index_code='000300.SH',trade_date='20261030',con_code=code,weight=weight)
                for code,weight in [('600000.SH',10),('000001.SZ',20),('300001.SZ',70)]]
    monkeypatch.setattr(linked.tushare_market,'rows',request)
    linked.save_observation(DAY,'09:30',{'600000.SH':.1,'000001.SZ':-.2})
    result=asyncio.run(linked.components(DAY,'csi300','09:30'))
    assert (result['covered'],result['total'],result['up'],result['down']) == (2,3,1,1)
    assert result['median'] == pytest.approx(-.05)
    assert result['weights_date'] == '20261030'
    assert result['leaders'][0]['contribution'] == pytest.approx(.01)
    asyncio.run(linked.components(DAY,'csi300','09:31'))
    assert calls == ['etf_sh_cons','index_weight']


def test_group_turnover_requires_every_fund_and_same_basket_history(monkeypatch):
    symbols=['510300.SH','510310.SH']
    saved={'members':symbols,'parts':{'510300.SH':{'data':{'09:30':5,'09:31':8}},'510310.SH':{'data':{'09:30':7}}}}
    historical={DAY:{code:{'data':dict.fromkeys(intraday.MINUTES, 1)} for code in symbols}}
    monkeypatch.setattr(intraday.store,'_read',lambda day:saved)
    monkeypatch.setattr(intraday,'baseline_basis',lambda day,saved:{'days':['2026-11-19']})
    monkeypatch.setattr(intraday.store,'_read_baseline_inputs',lambda days:(historical,{}))
    group=linked.grouped_turnover(DAY)[0]
    assert group['points']['09:30'] == 12
    assert group['points']['09:31'] is None
    assert group['baseline']['09:30'] == 2
    assert group['baseline']['09:31'] == 4


def test_components_api_rejects_future_and_non_session_minutes(storage, monkeypatch):
    monkeypatch.setattr(intraday,'now_cn',lambda:datetime(2026,11,19,10,0,tzinfo=intraday.CN))
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/components',params={'date':str(DAY),'group':'csi300','minute':'10:01'}).status_code == 422
        assert client.get('/components',params={'date':str(DAY),'group':'csi300','minute':'12:00'}).status_code == 422
        assert client.get('/components',params={'date':str(DAY),'group':'invalid','minute':'09:30'}).status_code == 422
