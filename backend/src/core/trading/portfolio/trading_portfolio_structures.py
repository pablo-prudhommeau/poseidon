from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class StablecoinSwapSettlementDirection(str, Enum):
    BUY_DEBIT = "BUY_DEBIT"
    SELL_CREDIT = "SELL_CREDIT"


class StablecoinSwapSettlementPollResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    swap_settled_on_chain: bool
    deployable_cash_usd: float
    transaction_signature: str


class LiveLiquiditySnapshotUnavailableError(Exception):
    pass


class TradingPortfolioValuation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deployable_cash_usd: float
    holdings_mark_to_market_usd: float
    wallet_auxiliary_assets_usd: float
    total_gas_refill_locked_stablecoin_usd: float
    sizing_capital_usd: float
    total_equity_value: float
