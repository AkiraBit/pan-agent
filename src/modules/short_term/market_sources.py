"""The short-term workbench's market-wide source chain."""

from marketdata.short_term import Batch, limit_pool as eastmoney_pool

from src.platform.marketdata import fuyao_business, fuyao_native


def limit_pool(kind: str, trade_date: str):
    partial = None
    for provider in fuyao_business.providers("market_sentiment", operation=fuyao_native.pool_operation(kind)):
        try:
            batch = fuyao_native.pool(kind, trade_date) if provider == "fuyao" else eastmoney_pool(kind, trade_date)
        except (RuntimeError, ValueError, TypeError, KeyError):
            continue
        if batch is None:
            continue
        if batch.status == "complete":
            return batch
        if partial is None or len(batch.rows) > len(partial.rows):
            partial = batch
    return partial or Batch(f"pool:{kind}", trade_date=trade_date, provider="unknown")
