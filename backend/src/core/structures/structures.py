from enum import Enum
from typing import List, Optional, Dict

from pydantic import BaseModel

from src.core.utils.format_utils import _tail
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger

logger = get_logger(__name__)


class Token(BaseModel):
    symbol: str
    chain: str
    token_address: str
    pair_address: str

    def __str__(self) -> str:
        return (f"[symbol={self.symbol} "
                f"chain={self.chain} "
                f"token_address={_tail(self.token_address)} "
                f"pair_address=…{_tail(self.pair_address)}]")

    def __hash__(self) -> int:
        return hash((self.chain, self.symbol, self.token_address, self.pair_address))


class Thresholds(BaseModel):
    take_profit_tier_1_price: float
    take_profit_tier_2_price: float
    stop_loss_price: float


class PreEntryDecision(BaseModel):
    is_valid_for_entry: bool
    decision_reason: str
    risk_diagnostics_map: dict[str, float]


class ScoreComponents(BaseModel):
    quality_score: float
    statistics_score: float
    entry_score: float

    def to_plain_dict(self) -> Dict[str, float]:
        return {
            "quality": float(self.quality_score),
            "statistics": float(self.statistics_score),
            "entry": float(self.entry_score),
        }


class Candidate(BaseModel):
    token: Token
    quality_score: float
    statistics_score: float
    entry_score: float
    final_computed_score: float
    score_components: ScoreComponents
    ai_quality_delta: float
    ai_buy_probability: float
    dexscreener_token_information: DexscreenerTokenInformation
    pair_address: Optional[str] = None
    dex_price: Optional[float] = None


class LifiEvmTransactionRequest(BaseModel):
    to: str
    data: str
    value: str
    gas: Optional[str] = None
    from_address: Optional[str] = None
    raw_transaction: Optional[str] = None


class LifiSolanaSerializedTransaction(BaseModel):
    serialized_transaction: str


class LifiRoute(BaseModel):
    transaction_request: LifiEvmTransactionRequest
    transaction: Optional[LifiSolanaSerializedTransaction] = None
    transactions: Optional[List[LifiSolanaSerializedTransaction]] = None
    serialized_transaction: Optional[str] = None
    from_address: Optional[str] = None


class OrderPayload(BaseModel):
    target_token: Token
    execution_price: float
    order_notional: float
    original_candidate: Candidate
    lifi_routing_path: Optional[LifiRoute] = None


class EvmTransactionRequest(BaseModel):
    recipient_address: str
    transaction_data: str
    value_in_wei: int
    forced_gas_limit: Optional[int] = None


class SolanaSerializedTransaction(BaseModel):
    serialized_payload_bytes: bytes


class RouteNetwork(Enum):
    EVM = "EVM"
    SOLANA = "SOLANA"


class Mode(Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class RiskDiagnostics(BaseModel):
    liquidity_usd: float
    percent_change_5m: float
    percent_change_1h: float
    percent_change_6h: float
    percent_change_24h: float
    buy_to_sell_ratio: float

    def as_plain_dict(self) -> dict:
        return {
            "liquidity_usd": float(self.liquidity_usd),
            "percent_change_5m": float(self.percent_change_5m),
            "percent_change_1h": float(self.percent_change_1h),
            "percent_change_6h": float(self.percent_change_6h),
            "percent_change_24h": float(self.percent_change_24h),
            "buy_to_sell_ratio": float(self.buy_to_sell_ratio)
        }


class RealizedProfitAndLoss(BaseModel):
    total_realized_profit_and_loss: float
    recent_realized_profit_and_loss: float


class CashFromTrades(BaseModel):
    available_cash: float
    total_buy_volume: float
    total_sell_volume: float
    total_fees_paid: float


class HoldingsAndUnrealizedProfitAndLoss(BaseModel):
    total_holdings_value: float
    total_unrealized_profit_and_loss: float


class EquityCurvePoint(BaseModel):
    timestamp_milliseconds: int
    equity: float


class EquityCurve(BaseModel):
    curve_points: list[EquityCurvePoint]


class WebsocketInboundMessage(BaseModel):
    type: str
    payload: Optional[dict] = None


class DcaStrategyStatus(Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DcaOrderStatus(Enum):
    PENDING = "PENDING"
    WAITING_USER_APPROVAL = "WAITING_USER_APPROVAL"
    APPROVED = "APPROVED"
    WITHDRAWN_FROM_AAVE = "WITHDRAWN_FROM_AAVE"
    SWAPPED = "SWAPPED"
    EXECUTED = "EXECUTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class DcaBacktestSeriesPoint(BaseModel):
    timestamp_iso: str
    execution_price: float
    average_purchase_price: float
    cumulative_spent: float
    dry_powder_remaining: float


class DcaBacktestMetadata(BaseModel):
    source_asset_symbol: str
    total_allocated_budget: float
    total_planned_executions: int
    final_dumb_average_unit_price: float
    final_smart_average_unit_price: float
    total_overheat_retentions: int


class DcaBacktestPayload(BaseModel):
    metadata: DcaBacktestMetadata
    dumb_dca_series: List[DcaBacktestSeriesPoint]
    smart_dca_series: List[DcaBacktestSeriesPoint]


class AllocationResult(BaseModel):
    spend_amount: float
    dry_powder_delta: float
    action_description: str
