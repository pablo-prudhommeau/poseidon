from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from src.core.utils.format_utils import tail


class BlockchainNetwork(str, Enum):
    SOLANA = "solana"
    BSC = "bsc"
    BASE = "base"
    AVALANCHE = "avalanche"


class Token(BaseModel):
    symbol: str
    chain: BlockchainNetwork
    token_address: str
    pair_address: str
    dex_id: str

    def __str__(self) -> str:
        return (f"[symbol={self.symbol} "
                f"chain={self.chain.value} "
                f"dex_id={self.dex_id} "
                f"token_address={tail(self.token_address)} "
                f"pair_address=…{tail(self.pair_address)}]")

    def __hash__(self) -> int:
        return hash((self.chain, self.dex_id, self.symbol, self.token_address, self.pair_address))


class Mode(Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


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


class WebsocketMessageType(str, Enum):
    INITIALIZATION = "initialization"
    PORTFOLIO = "portfolio"
    LIQUIDITY = "liquidity"
    SHADOW_META = "shadow_meta"
    SHADOW_VERDICT_CHRONICLE = "shadow_verdict_chronicle"
    SHADOW_VERDICT_CHRONICLE_DELTA = "shadow_verdict_chronicle_delta"
    POSITIONS = "positions"
    TRADES = "trades"
    DCA_STRATEGIES = "dca_strategies"
    PONG = "pong"
    ERROR = "error"
    REFRESH = "refresh"
    PING = "ping"


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
