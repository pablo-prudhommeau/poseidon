from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.core.structures.structures import Token
from src.core.trading.screener.trading_screener_structures import TradingScreenerEnvelope
from src.core.trading.shadowing.trading_shadowing_structures import TradingCandidateShadowingDiagnostics
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute


class PositionExitTriggerReason(str, enum.Enum):
    TAKE_PROFIT_1 = "TAKE_PROFIT_1"
    TAKE_PROFIT_2 = "TAKE_PROFIT_2"
    STOP_LOSS = "STOP_LOSS"
    MANUAL = "MANUAL"
    KILLED = "KILLED"
    HONEYPOT = "HONEYPOT"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    WALLET_BALANCE_EMPTY = "WALLET_BALANCE_EMPTY"


class TradingFilterVerdict(BaseModel):
    is_accepted: bool
    rejection_reasons: List[str]


class TradingCortexInferenceSnapshot(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    success_probability: float
    toxicity_probability: float
    expected_profit_and_loss_percentage: float
    predicted_holding_time_minutes: float
    final_trade_score: float
    model_version: str
    model_ready: bool
    gate_verdict: TradingFilterVerdict


class TradingDexMarketSnapshot(BaseModel):
    price_usd: float
    price_native: float
    token_age_hours: float
    volume_m5_usd: float
    volume_h1_usd: float
    volume_h6_usd: float
    volume_h24_usd: float
    liquidity_usd: float
    price_change_percentage_m5: float
    price_change_percentage_h1: float
    price_change_percentage_h6: float
    price_change_percentage_h24: float
    transaction_count_m5: int
    transaction_count_h1: int
    transaction_count_h6: int
    transaction_count_h24: int
    buy_to_sell_ratio: float
    market_cap_usd: float
    fully_diluted_valuation_usd: float
    promotion_score: Optional[float] = None


class TradingCandidateAiAnalysis(BaseModel):
    adjusted_quality_score: float = 0.0
    quality_delta: float = 0.0
    buy_probability: float = 0.0


class TradingCandidateCortexDiagnostics(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    inference_snapshot: Optional[TradingCortexInferenceSnapshot] = None


class TradingCandidate(BaseModel):
    token: Token
    market_snapshot: TradingDexMarketSnapshot
    screener_envelope: TradingScreenerEnvelope
    screened_price_usd: Optional[float] = None
    quality_score: float = 0.0
    ai_analysis: TradingCandidateAiAnalysis = Field(default_factory=TradingCandidateAiAnalysis)
    shadowing_diagnostics: TradingCandidateShadowingDiagnostics = Field(default_factory=TradingCandidateShadowingDiagnostics)
    cortex_diagnostics: TradingCandidateCortexDiagnostics = Field(default_factory=TradingCandidateCortexDiagnostics)


class TradingPreEntryDecision(BaseModel):
    is_valid_for_entry: bool
    decision_reason: str


class TradingOrderPayload(BaseModel):
    target_token: Token
    execution_price: float
    order_notional: float
    original_candidate: TradingCandidate
    origin_evaluation_id: int
    execution_route: Optional[BlockchainExecutionRoute] = None


class TradingPortfolioEquityCurvePoint(BaseModel):
    timestamp_milliseconds: int
    total_equity_value: float


class TradingPortfolio(BaseModel):
    total_equity_value: float
    deployable_cash_usd: float
    holdings_mark_to_market_usd: float
    wallet_auxiliary_assets_usd: float
    total_gas_refill_locked_stablecoin_usd: float
    sizing_capital_usd: float
    cumulative_swap_fees_usd: float
    created_at: datetime
    equity_curve: list[TradingPortfolioEquityCurvePoint] = Field(default_factory=list)
    unrealized_profit_and_loss: float = 0.0
    realized_profit_and_loss_24h: float = 0.0
    realized_profit_and_loss_7d: float = 0.0
    realized_profit_and_loss_30d: float = 0.0
    realized_profit_and_loss_total: float = 0.0


class TradingConfigurationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class GasRefillBudgetDetailScope(str, enum.Enum):
    SOLANA_WITH_TOKEN_ACCOUNT_RENT = "solana_with_token_account_rent"
    EVM_SWAP_FEES_ONLY = "evm_swap_fees_only"


class TradingApplicationBootConfigurationSettings(Protocol):
    TRADING_ALLOWED_CHAINS: list[str]
    TRADING_SOLANA_SUPPORTED_DEX_IDS: list[str]
    PAPER_MODE: bool
    WALLET_MNEMONIC: str
    WALLET_DERIVATION_INDEX: int
    TRADING_STABLECOIN_ADDRESS_SOLANA: str
    TRADING_STABLECOIN_ADDRESS_BSC: str
    TRADING_STABLECOIN_ADDRESS_BASE: str
    TRADING_STABLECOIN_ADDRESS_AVALANCHE: str
