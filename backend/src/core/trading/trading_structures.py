from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, List

from pydantic import BaseModel

from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceSnapshotPayload
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation


class AutosellTriggerReason(str, enum.Enum):
    TAKE_PROFIT_1 = "TAKE_PROFIT_1"
    TAKE_PROFIT_2 = "TAKE_PROFIT_2"
    STOP_LOSS = "STOP_LOSS"


class TradingFilterVerdict(BaseModel):
    is_accepted: bool
    rejection_reasons: List[str]


class ShadowDiagnostics(BaseModel):
    toxic_metric_count: int = 0
    total_metrics_evaluated: int = 0
    toxic_metric_keys: list[str] = []
    golden_metric_keys: list[str] = []
    notional_boost_factor: float = 1.0
    intelligence_snapshot: Optional[ShadowIntelligenceSnapshotPayload] = None


class TradingCandidate(BaseModel):
    token: Token
    quality_score: float
    ai_adjusted_quality_score: float
    ai_quality_delta: float
    ai_buy_probability: float
    shadow_notional_multiplier: float = 1.0
    shadow_diagnostics: ShadowDiagnostics = ShadowDiagnostics()
    dexscreener_token_information: DexscreenerTokenInformation
    pair_address: Optional[str] = None
    dex_price: Optional[float] = None


class TradingRiskDiagnostics(BaseModel):
    liquidity_usd: float
    percent_change_5m: float
    percent_change_1h: float
    percent_change_6h: float
    percent_change_24h: float
    buy_to_sell_ratio: float

    def as_plain_dict(self) -> dict[str, float]:
        return {
            "liquidity_usd": self.liquidity_usd,
            "percent_change_5m": self.percent_change_5m,
            "percent_change_1h": self.percent_change_1h,
            "percent_change_6h": self.percent_change_6h,
            "percent_change_24h": self.percent_change_24h,
            "buy_to_sell_ratio": self.buy_to_sell_ratio,
        }


class TradingPreEntryDecision(BaseModel):
    is_valid_for_entry: bool
    decision_reason: str
    risk_diagnostics_map: dict[str, float]


class TradingThresholds(BaseModel):
    take_profit_tier_1_price: float
    take_profit_tier_2_price: float
    stop_loss_price: float


class TradingLifiEvmTransactionRequest(BaseModel):
    to: str
    data: str
    value: str
    gas: Optional[str] = None
    from_address: Optional[str] = None
    raw_transaction: Optional[str] = None


class TradingSolanaRoute(BaseModel):
    serialized_transaction_base64: str


class TradingEvmRoute(BaseModel):
    transaction_request: TradingLifiEvmTransactionRequest


class TradingExecutionRoute(BaseModel):
    evm_route: Optional[TradingEvmRoute] = None
    solana_route: Optional[TradingSolanaRoute] = None


class TradingOrderPayload(BaseModel):
    target_token: Token
    execution_price: float
    order_notional: float
    original_candidate: TradingCandidate
    origin_evaluation_id: int
    execution_route: Optional[TradingExecutionRoute] = None


class TradingEvmTransactionRequest(BaseModel):
    recipient_address: str
    transaction_data: str
    value_in_wei: int
    forced_gas_limit: Optional[int] = None


class TradingSolanaSerializedTransaction(BaseModel):
    serialized_payload_bytes: bytes


class TradingQualityContext(BaseModel):
    liquidity_usd: float
    volume_m5_usd: float
    volume_h1_usd: float
    volume_h6_usd: float
    volume_h24_usd: float
    age_hours: float
    percent_m5: float
    percent_h1: float
    percent_h6: float
    percent_h24: float
    momentum_score: float
    liquidity_score: float
    volume_score: float
    order_flow_score: float


class TradingQualityResult(BaseModel):
    is_admissible: bool
    score: float
    rejection_reason: str
    context: TradingQualityContext


@dataclass(frozen=True)
class TradingExecutionResult:
    network: str
    transaction_hash_or_signature: str


class TradingPipelineContext(BaseModel):
    token_price_information_list: list[DexscreenerTokenInformation] = []
    shadow_intelligence_snapshot: Optional[object] = None
    free_cash_usd: float = 0.0
    per_order_budget_usd: float = 0.0
    executed_buy_count: int = 0

    class Config:
        arbitrary_types_allowed = True


@dataclass
class InventoryLot:
    quantity: float
    unit_price_usd: float
    buy_fee_per_unit_usd: float


from src.core.structures.structures import Token

TradingCandidate.model_rebuild()
TradingOrderPayload.model_rebuild()
