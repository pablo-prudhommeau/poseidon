from dataclasses import dataclass
from enum import Enum
from typing import Mapping, List, Optional, Any, Dict

from pydantic import BaseModel

from src.core.utils.format_utils import _tail
from src.logging.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Token:
    symbol: str
    chain: str
    tokenAddress: str
    pairAddress: str

    def __str__(self) -> str:
        return (f"[{self.symbol} "
                f"chain={self.chain} "
                f"tokenAddress={_tail(self.tokenAddress)} "
                f"pairAddress=…{_tail(self.pairAddress)}]")

    def __hash__(self) -> int:
        return hash((self.chain, self.symbol, self.tokenAddress, self.pairAddress))


class TransactionBucket:
    """
    Aggregated buy/sell counts (or notional) in a time bucket.
    """
    buys: float
    sells: float

    def to_plain_dict(self) -> Dict[str, float]:
        return {
            "buys": float(self.buys),
            "sells": float(self.sells),
        }


class TransactionSummary:
    """
    Summary of recent activity over canonical windows.
    All fields are optional to gracefully handle partial payloads.
    """
    m5: Optional[TransactionBucket]
    h1: Optional[TransactionBucket]
    h6: Optional[TransactionBucket]
    h24: Optional[TransactionBucket]

    def to_plain_dict(self) -> Dict[str, Dict[str, float]]:
        def conv(bucket: Optional[TransactionBucket]) -> Dict[str, float]:
            return bucket.to_plain_dict() if bucket is not None else {}

        return {
            "m5": conv(self.m5),
            "h1": conv(self.h1),
            "h6": conv(self.h6),
            "h24": conv(self.h24),
        }


class CandidateMarketData:
    """
    Minimal structural contract for the market data we require during risk checks.
    Extra keys are allowed by design.
    """
    symbol: str
    liqUsd: float
    pct5m: float
    pct1h: float
    sparkline5m: List[float]
    sparkline30m: List[float]
    prices: List[float]
    sparkline: List[float]
    txns: TransactionSummary


class CandidateScoringInput:
    """
    Minimal structural contract for scoring/quality checks.
    Extra keys are allowed. Some keys may be missing depending on sources.
    """
    symbol: str
    address: str
    liqUsd: float
    vol24h: float
    pairCreatedAt: int
    pct5m: float
    pct1h: float
    pct24h: float
    txns: TransactionSummary
    m1: object
    m5: object
    qualityScore: float


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
    """
    Strongly-typed view over a trending candidate.

    This class provides readable attribute names while preserving back-compat with
    the rest of the codebase that still expects Dexscreener-style keys. Use
    :meth:`to_source_dict` when calling legacy helpers, and keep the rest of the
    pipeline using attribute access exclusively.
    """
    symbol: str
    chain_name: str
    token_address: str
    pair_address: str
    price_usd: float
    price_native: float
    volume_24h_usd: float
    liquidity_usd: float
    percent_5m: float
    percent_1h: float
    percent_24h: float
    pair_created_at_epoch_seconds: int
    token_age_hours: float
    quality_score: float
    statistics_score: float
    entry_score: float
    score_final: float
    score_components: ScoreComponents
    ai_quality_delta: float
    ai_buy_probability: float
    txns: TransactionSummary

    def to_source_dict(self) -> Dict[str, Any]:
        """
        Convert this Candidate back into the Dexscreener-style dict that legacy
        helpers expect. All nested objects are converted to JSON-serializable
        primitives (dict/float/str/bool).
        """
        score_components_dict: Dict[str, float] = (
            self.score_components.to_plain_dict() if self.score_components is not None else {}
        )
        txns_dict: Dict[str, Dict[str, float]] = (
            self.txns.to_plain_dict() if self.txns is not None else {}
        )

        return {
            "symbol": self.symbol,
            "chain": self.chain_name,
            "tokenAddress": self.token_address,
            "pairAddress": self.pair_address,
            "priceUsd": float(self.price_usd),
            "priceNative": float(self.price_native),
            "volume24hUsd": float(self.volume_24h_usd),
            "liquidityUsd": float(self.liquidity_usd),
            "pct5m": float(self.percent_5m),
            "pct1h": float(self.percent_1h),
            "pct24h": float(self.percent_24h),
            "pairCreatedAt": int(self.pair_created_at_epoch_seconds),
            "token_age_hours": float(self.token_age_hours),
            "qualityScore": float(self.quality_score),
            "statScore": float(self.statistics_score),
            "entryScore": float(self.entry_score),
            "scoreFinal": float(self.score_final),
            "scoreComponents": score_components_dict,
            "aiDelta": float(self.ai_quality_delta),
            "aiBuyProb": float(self.ai_buy_probability),
            "txns": txns_dict,
        }


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
    buy_ratio: float

    def as_plain_dict(self) -> dict:
        return {
            "liq": float(self.liquidity_usd),
            "pct5m": float(self.percent_5m),
            "pct1h": float(self.percent_1h),
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
