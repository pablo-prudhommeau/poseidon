from dataclasses import dataclass
from enum import Enum
from typing import Mapping, List, Optional, Any, Dict

from pydantic import BaseModel

from src.core.utils.format_utils import _tail
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Token:
    symbol: str
    chain: str
    tokenAddress: str
    pairAddress: str

    def __str__(self) -> str:
        return (f"[symbol={self.symbol} "
                f"chain={self.chain} "
                f"tokenAddress={_tail(self.tokenAddress)} "
                f"pairAddress=…{_tail(self.pairAddress)}]")

    def __hash__(self) -> int:
        return hash((self.chain, self.symbol, self.tokenAddress, self.pairAddress))


@dataclass
class Thresholds:
    take_profit_tp1: float
    take_profit_tp2: float
    stop_loss: float


@dataclass
class PreEntryDecision:
    should_buy: bool
    reason: str
    diagnostics: Mapping[str, float]


@dataclass(frozen=True)
class ScoreComponents:
    quality_score: float
    statistics_score: float
    entry_score: float

    def to_plain_dict(self) -> Dict[str, float]:
        return {
            "quality": float(self.quality_score),
            "statistics": float(self.statistics_score),
            "entry": float(self.entry_score),
        }


@dataclass
class Candidate:
    token: Token
    quality_score: float
    statistics_score: float
    entry_score: float
    score_final: float
    score_components: ScoreComponents
    ai_quality_delta: float
    ai_buy_probability: float
    dexscreener_token_information: DexscreenerTokenInformation


class LifiEvmTransactionRequest:
    to: str
    data: str
    value: str
    from_: str


class LifiSolanaSerializedTx:
    serializedTransaction: str


@dataclass
class LifiRoute:
    transactionRequest: LifiEvmTransactionRequest
    transaction: Optional[LifiSolanaSerializedTx] = None
    transactions: Optional[List[LifiSolanaSerializedTx]] = None


@dataclass
class OrderPayload:
    token: Token
    price: float
    order_notional: float
    original_candidate: Candidate
    lifi_route: LifiRoute


@dataclass(frozen=True)
class EvmTransactionRequest:
    to: str
    data: str
    value_wei: int
    gas_limit: Optional[int] = None


@dataclass(frozen=True)
class SolanaSerializedTransaction:
    payload: bytes


class RouteNetwork(Enum):
    EVM = "EVM"
    SOLANA = "SOLANA"


class Mode(Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass(frozen=True)
class RiskDiagnostics:
    liquidity_usd: float
    percent_5m: float
    percent_1h: float
    percent_6h: float
    percent_24h: float
    buy_ratio: float

    def as_plain_dict(self) -> dict:
        return {
            "liq": float(self.liquidity_usd),
            "pct5m": float(self.percent_5m),
            "pct1h": float(self.percent_1h),
            "pct6h": float(self.percent_6h),
            "pct24h": float(self.percent_24h),
            "buy_ratio": float(self.buy_ratio)
        }


@dataclass(frozen=True)
class RealizedPnl:
    total: float
    recent: float


@dataclass(frozen=True)
class CashFromTrades:
    cash: float
    total_buys: float
    total_sells: float
    total_fees: float


@dataclass(frozen=True)
class HoldingsAndUnrealizedPnl:
    holdings: float
    unrealized_pnl: float


@dataclass(frozen=True)
class EquityCurvePoint:
    timestamp: int
    equity: float


@dataclass(frozen=True)
class EquityCurve:
    points: List[EquityCurvePoint]


class WebsocketInboundMessage(BaseModel):
    type: str
    payload: Optional[Dict[str, Any]] = None


class DcaStrategyStatus(Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DcaOrderStatus(Enum):
    """Lifecycle states of an individual DCA execution with idempotent pipeline tracking."""
    PENDING = "PENDING"
    WAITING_USER_APPROVAL = "WAITING_USER_APPROVAL"
    APPROVED = "APPROVED"
    WITHDRAWN_FROM_AAVE = "WITHDRAWN_FROM_AAVE"
    SWAPPED = "SWAPPED"
    EXECUTED = "EXECUTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class DcaBacktestSeriesPoint(BaseModel):
    timestamp_iso: str
    execution_price: float
    average_purchase_price: float
    cumulative_spent: float
    dry_powder_remaining: float


class DcaBacktestMetadata(BaseModel):
    symbol: str
    total_budget: float
    executions: int
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
