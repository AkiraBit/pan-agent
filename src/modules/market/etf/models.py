from sqlalchemy import Column, Float, ForeignKey, Integer, JSON, String, Text

from src.platform.persistence.database import Base


class EtfSnapshot(Base):
    __tablename__ = 'etf_source_snapshots'
    id = Column(Integer, primary_key=True)
    resource = Column(String, nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)
    source_url = Column(Text, nullable=False)
    source_updated_at = Column(String)
    observed_at = Column(String, nullable=False, index=True)
    checksum = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)


class EtfDaily(Base):
    """Latest normalized observation; money in CNY, quantities in fund units."""
    __tablename__ = 'etf_daily'
    code = Column(String, primary_key=True)
    trade_date = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    index_name = Column(String, nullable=False)
    close = Column(Float)
    change_percent = Column(Float)
    turnover_cny = Column(Float)
    shares_delta = Column(Float)
    net_subscription_estimate_cny = Column(Float)
    scale_cny = Column(Float)
    peak_ratio = Column(Float)
    snapshot_id = Column(Integer, ForeignKey('etf_source_snapshots.id'), nullable=False)


class EtfMinute(Base):
    __tablename__ = 'etf_basket_minutes'
    trade_date = Column(String, primary_key=True)
    time = Column(String, primary_key=True)
    turnover_cny = Column(Float, nullable=False)
    baseline_turnover_cny = Column(Float)
    snapshot_id = Column(Integer, ForeignKey('etf_source_snapshots.id'), nullable=False)


class EtfTurnover(Base):
    """Latest supplemental daily turnover, with independent source provenance."""
    __tablename__ = 'etf_turnover_daily'
    code = Column(String, primary_key=True)
    trade_date = Column(String, primary_key=True)
    turnover_cny = Column(Float, nullable=False)
    snapshot_id = Column(Integer, ForeignKey('etf_source_snapshots.id'), nullable=False)
    checked_at = Column(String, nullable=False)


class EtfFlowDay(Base):
    __tablename__ = 'etf_basket_daily'
    trade_date = Column(String, primary_key=True)
    covered = Column(Integer, nullable=False)
    net_subscription_estimate_cny = Column(Float)
    index_close = Column(Float)
    index_change_percent = Column(Float)
    peak_ratio = Column(Float)
    snapshot_id = Column(Integer, ForeignKey('etf_source_snapshots.id'), nullable=False)


class EtfHolding(Base):
    """Versioned named disclosures. Missing from a top-ten table is NOT a sale."""
    __tablename__ = 'etf_holder_disclosures'
    snapshot_id = Column(Integer, ForeignKey('etf_source_snapshots.id'), primary_key=True)
    holder_name = Column(String, primary_key=True)
    code = Column(String, nullable=False, index=True)
    report_date = Column(String, nullable=False, index=True)
    shares = Column(Float, nullable=False)
    ratio_percent = Column(Float, nullable=False)
    institution = Column(String, index=True)
    # A provider without announcement dates cannot support historical knowledge claims.
    announced_at = Column(String)
    known_from = Column(String, nullable=False, index=True)
