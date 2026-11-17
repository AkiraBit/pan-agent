"""Apply provider pauses without changing endpoint preferences or call order."""

from sqlalchemy import and_, case, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from src.platform.persistence.models import DataSource, DataSourceProviderPause

PROVIDER_ALIASES = {"eastmoney_news": "eastmoney", "ths": "fuyao"}
REGISTERED_PROVIDERS = {"fuyao", "ftshare", "cls", "eastmoney", "tencent", "sina"}
RETIRED_TYPES = {"etf_shares", "etf_pcf"}


def supported_provider(provider: str) -> bool:
    return provider_group(provider) in REGISTERED_PROVIDERS


def provider_group(provider: str) -> str:
    return PROVIDER_ALIASES.get(provider, provider)


def provider_group_column():
    return case(PROVIDER_ALIASES, value=DataSource.provider, else_=DataSource.provider)


def active_source():
    return and_(
        DataSource.enabled.is_(True),
        DataSource.type.not_in(RETIRED_TYPES),
        provider_group_column().in_(REGISTERED_PROVIDERS),
        provider_group_column().not_in(select(DataSourceProviderPause.provider)),
    )


def paused_providers(db: Session) -> set[str]:
    return set(db.scalars(select(DataSourceProviderPause.provider).where(
        DataSourceProviderPause.provider.in_(REGISTERED_PROVIDERS)
    )))


def set_provider_enabled(db: Session, provider: str, enabled: bool) -> None:
    if enabled:
        pause = db.get(DataSourceProviderPause, provider)
        if pause is not None:
            db.delete(pause)
    else:
        db.execute(insert(DataSourceProviderPause).values(provider=provider).on_conflict_do_nothing())
    db.commit()
