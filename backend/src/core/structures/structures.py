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
    """Per-position thresholds computed ex-ante."""
    take_profit_tp1: float
    take_profit_tp2: float
    stop_loss: float


@dataclass
class PreEntryDecision:
    """Decision and diagnostics for whether a buy should occur now."""
    should_buy: bool
    reason: str
    diagnostics: Mapping[str, float]


@dataclass(frozen=True)
class ScoreComponents:
    """Normalized scoring components attached to a candidate."""
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
    """Minimal LI.FI EVM request shape (kept deliberately loose but typed)."""
    to: str
    data: str
    value: str
    from_: str


class LifiSolanaSerializedTx:
    """Container for a base64-encoded Solana transaction."""
    serializedTransaction: str


@dataclass
class LifiRoute:
    """
    Unified LI.FI route envelope supporting both EVM and Solana flavors.
    Only the keys used to infer the network or execute the route are modeled.
    """
    transactionRequest: LifiEvmTransactionRequest
    transaction: Optional[LifiSolanaSerializedTx] = None
    transactions: Optional[List[LifiSolanaSerializedTx]] = None


@dataclass
class OrderPayload:
    """
    Typed input contract expected by Trader.buy().
    Upstream (e.g. TrendingJob) typically provides these fields.
    """
    token: Token
    price: float
    order_notional: float
    original_candidate: Candidate
    lifi_route: LifiRoute


@dataclass(frozen=True)
class EvmTransactionRequest:
    """Canonical EVM transaction payload extracted from a LI.FI route."""
    to: str
    data: str
    value_wei: int
    gas_limit: Optional[int] = None


@dataclass(frozen=True)
class SolanaSerializedTransaction:
    """Canonical Solana transaction extracted from a LI.FI route."""
    payload: bytes


class RouteNetwork(Enum):
    """Supported network families for LI.FI execution."""
    EVM = "EVM"
    SOLANA = "SOLANA"


class Mode(Enum):
    """Trading modes."""
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass(frozen=True)
class RiskDiagnostics:
    """
    Diagnostics payload for risk decisions.
    Kept strongly-typed; converted to a plain dict only when constructing
    PreEntryDecision (for compatibility with existing code paths).
    """
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
    """
    Realized PnL results from processing a set of trades.
    """
    total: float
    recent: float


@dataclass(frozen=True)
class CashFromTrades:
    """
    Cash flow results from processing a set of trades.
    """
    cash: float
    total_buys: float
    total_sells: float
    total_fees: float


@dataclass(frozen=True)
class HoldingsAndUnrealizedPnl:
    """
    Holdings and unrealized PnL results.
    """
    holdings: float
    unrealized_pnl: float


@dataclass(frozen=True)
class EquityCurvePoint:
    """
    Equity curve point as (timestamp, equity) tuple.
    """
    timestamp: int
    equity: float


@dataclass(frozen=True)
class EquityCurve:
    """
    Equity curve as a list of (timestamp, equity) points.
    """
    points: List[EquityCurvePoint]


class WebsocketInboundMessage(BaseModel):
    """
    Strictly typed websocket inbound message structure.
    """
    type: str
    payload: Optional[Dict[str, Any]] = None
