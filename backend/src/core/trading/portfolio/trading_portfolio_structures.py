from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SolanaTokenAccountRentBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_usd: float
    closable_usd: float
    pending_reclaim_usd: float
    locked_sol: float
    active_account_count: int
    closable_account_count: int
    pending_reclaim_account_count: int


class TradingPortfolioValuation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deployable_cash_usd: float
    holdings_mark_to_market_usd: float
    wallet_auxiliary_assets_usd: float
    sizing_capital_usd: float
    total_equity_value: float
