"""Durable Tushare ETF snapshots. The previous FTShare table is never read."""
from sqlalchemy import Column, Integer, JSON, String, text

from src.platform.persistence.database import Base


class EtfIntradayDay(Base):
    __tablename__ = "etf_tushare_intraday_days"

    trade_date = Column(String(10), primary_key=True)
    # Independent components keep successful reads when a sibling endpoint fails.
    parts = Column(JSON, nullable=False)
    turnover_revision = Column(Integer, nullable=False, server_default=text("0"))


class EtfTurnoverBaseline(Base):
    __tablename__ = "etf_tushare_turnover_baselines"

    trade_date = Column(String(10), primary_key=True)
    payload = Column(JSON, nullable=False)


class EtfPriceSession(Base):
    __tablename__ = "etf_tushare_price_sessions"

    trade_date = Column(String(10), primary_key=True)
    symbol = Column(String(9), primary_key=True)
    payload = Column(JSON, nullable=False)


class IndexPriceSession(Base):
    __tablename__ = "etf_tushare_index_price_sessions"

    trade_date = Column(String(10), primary_key=True)
    symbol = Column(String(9), primary_key=True)
    payload = Column(JSON, nullable=False)


class EtfTushareUniverse(Base):
    __tablename__ = "etf_tushare_universes"

    key = Column(String, primary_key=True)
    updated_on = Column(String(10), nullable=False)
    payload = Column(JSON, nullable=False)
