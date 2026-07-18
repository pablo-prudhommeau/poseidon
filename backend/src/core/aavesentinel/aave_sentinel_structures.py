from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.utils.date_utils import get_current_local_datetime


class AaveSentinelStrategyKind(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class AaveSentinelNonTradingMovementSource(str, Enum):
    INTEREST_ACCRUAL = "INTEREST_ACCRUAL"
    GAS_FEES = "GAS_FEES"
    SLIPPAGE = "SLIPPAGE"
    ORACLE_PRICE_GAP = "ORACLE_PRICE_GAP"


class AaveSentinelPnlTimelineBlockKind(str, Enum):
    STRATEGY = "STRATEGY"
    NON_TRADING_PERIOD = "NON_TRADING_PERIOD"


class AaveSentinelRiskStatus(str, Enum):
    OPTIMAL = "OPTIMAL"
    NEUTRAL = "NEUTRAL"
    WARNING = "WARNING"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"


class AaveSentinelAlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    DANGER = "DANGER"
    SUCCESS = "SUCCESS"
    CRITICAL = "CRITICAL"


class AaveSentinelConfigurationError(RuntimeError):
    pass


class AaveSentinelAssetSnapshot(BaseModel):
    symbol: str
    underlying_address: str
    supply_amount: float
    debt_amount: float
    wallet_amount: float
    supply_value_usd: float
    debt_value_usd: float
    wallet_value_usd: float
    supply_annual_percentage_yield: float
    borrow_annual_percentage_yield: float
    liquidation_threshold: float = 0.0


class AaveSentinelStrategy(BaseModel):
    kind: AaveSentinelStrategyKind
    main_asset_symbol: str
    main_asset_price_usd: float
    liquidation_price_usd: float
    leverage: float
    collateral_usd: float
    debt_usd: float


class AaveSentinelPositionSnapshot(BaseModel):
    health_factor: float
    total_collateral_usd: float
    total_debt_usd: float
    strategies: list[AaveSentinelStrategy] = Field(default_factory=list)
    assets: list[AaveSentinelAssetSnapshot] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=get_current_local_datetime)


class AaveSentinelNotificationState(BaseModel):
    last_risk_status: AaveSentinelRiskStatus = AaveSentinelRiskStatus.OPTIMAL
    last_health_factor: Optional[float] = None
    last_total_equity_usd: Optional[float] = None
    last_notification_time: Optional[datetime] = None


class AaveSentinelCapitalFlowDirection(str, Enum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class AaveSentinelReserveAsset(BaseModel):
    model_config = ConfigDict(frozen=True)

    underlying_address: str
    symbol: str
    decimal_count: int
    requires_euro_conversion: bool
    a_token_address: str
    stable_debt_token_address: str
    variable_debt_token_address: str


class AaveSentinelReserveRegistry(BaseModel):
    model_config = ConfigDict(frozen=True)

    reserve_assets: tuple[AaveSentinelReserveAsset, ...] = Field(default_factory=tuple)


class AaveSentinelErc20TransferFlow(BaseModel):
    incoming_amount: float = 0.0
    outgoing_amount: float = 0.0


class AaveSentinelErc20TransferFlowRecord(BaseModel):
    contract_address: str
    transfer_flow: AaveSentinelErc20TransferFlow = Field(default_factory=AaveSentinelErc20TransferFlow)


class AaveSentinelUniversalLedgerEntry(BaseModel):
    transaction_hash: str
    block_number: int = 0
    timestamp_seconds: int = 0
    native_sent_amount: float = 0.0
    native_received_amount: float = 0.0
    gas_fee_native_amount: float = 0.0
    erc20_transfer_flows: list[AaveSentinelErc20TransferFlowRecord] = Field(default_factory=list)


class AaveSentinelIntervalForensicBreakdown(BaseModel):
    window_start_timestamp_seconds: int
    window_end_timestamp_seconds: int
    gas_fee_usd: float = 0.0
    conversion_pnl_usd: float = 0.0


class AaveSentinelUniversalLedger(BaseModel):
    entries: list[AaveSentinelUniversalLedgerEntry] = Field(default_factory=list)


class AaveSentinelEuroConversionContext(BaseModel):
    block_number: int
    timestamp_seconds: int


class AaveSentinelHistoricalAssetPriceLookupKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    block_number: int
    contract_address: str


class AaveSentinelBlockExchangeRateMemoEntry(BaseModel):
    block_number: int
    exchange_rate: float


class AaveSentinelDateExchangeRateMemoEntry(BaseModel):
    exchange_rate_date: str
    exchange_rate: float


class AaveSentinelHistoricalAssetPriceMemoEntry(BaseModel):
    lookup_key: AaveSentinelHistoricalAssetPriceLookupKey
    asset_price_usd: float


class AaveSentinelBlockTimestampMemoEntry(BaseModel):
    block_number: int
    timestamp_seconds: int


class AaveSentinelForensicTimestampWindow(BaseModel):
    started_at_timestamp_seconds: int
    ended_at_timestamp_seconds: int


class AaveSentinelOraclePriceGapAssetContribution(BaseModel):
    underlying_address: str
    asset_symbol: Optional[str] = None
    pnl_usd: float = 0.0


class AaveSentinelNonTradingPeriodSourceBreakdown(BaseModel):
    source: AaveSentinelNonTradingMovementSource
    pnl_usd: float = 0.0
    dominant_asset_symbol: Optional[str] = None


class AaveSentinelNonTradingPeriodSummary(BaseModel):
    started_at_timestamp_seconds: int
    ended_at_timestamp_seconds: int
    total_pnl_usd: float = 0.0
    source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown] = Field(default_factory=list)


class AaveSentinelPnlTimelineBlock(BaseModel):
    kind: AaveSentinelPnlTimelineBlockKind
    sort_timestamp_seconds: int
    sort_index: int
    lines: list[str] = Field(default_factory=list)


class AaveSentinelCapitalFlowValuationMemo(BaseModel):
    block_exchange_rates: list[AaveSentinelBlockExchangeRateMemoEntry] = Field(default_factory=list)
    date_exchange_rates: list[AaveSentinelDateExchangeRateMemoEntry] = Field(default_factory=list)
    historical_asset_prices: list[AaveSentinelHistoricalAssetPriceMemoEntry] = Field(default_factory=list)
    block_timestamps: list[AaveSentinelBlockTimestampMemoEntry] = Field(default_factory=list)


class AaveSentinelTransactionHeadFingerprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    latest_normal_transaction_hash: str
    latest_internal_transaction_hash: str
    latest_token_transaction_hash: str


class AaveSentinelCapitalFlowValuationContext(BaseModel):
    contract_address: Optional[str]
    asset_symbol: str
    block_number: int
    timestamp_seconds: int
    token_amount: float
    requires_euro_conversion: bool


class AaveSentinelClassifiedCapitalFlow(BaseModel):
    transaction_hash: str
    block_number: int
    timestamp_seconds: int
    asset_symbol: str
    contract_address: Optional[str]
    direction: AaveSentinelCapitalFlowDirection
    token_amount: float
    amount_usd: float


class AaveSentinelRawCapitalFlowEvent(BaseModel):
    transaction_hash: str
    block_number: int
    timestamp_seconds: int
    contract_address: Optional[str]
    asset_symbol: str
    direction: AaveSentinelCapitalFlowDirection
    token_amount: float
    requires_euro_conversion: bool


class AaveSentinelAssetFlowTotals(BaseModel):
    asset_symbol: str
    total_inflow_token_amount: float = 0.0
    total_outflow_token_amount: float = 0.0
    total_inflow_usd: float = 0.0
    total_outflow_usd: float = 0.0


class AaveSentinelCapitalFlowSummary(BaseModel):
    total_inflow_usd: float = 0.0
    total_outflow_usd: float = 0.0
    net_capital_deployed_usd: float = 0.0
    asset_flow_totals: list[AaveSentinelAssetFlowTotals] = Field(default_factory=list)
    classified_flows: list[AaveSentinelClassifiedCapitalFlow] = Field(default_factory=list)
    is_available: bool = False
    refreshed_at: Optional[datetime] = None


class AaveSentinelReserveInterestBreakdown(BaseModel):
    asset_symbol: str
    supply_interest_usd: float = 0.0
    borrow_interest_usd: float = 0.0
    net_interest_usd: float = 0.0


class AaveSentinelStrategyCycleSummary(BaseModel):
    kind: AaveSentinelStrategyKind
    main_asset_symbol: Optional[str] = None
    leverage: float = 0.0
    opened_at_timestamp_seconds: int
    closed_at_timestamp_seconds: Optional[int] = None
    is_open: bool = False
    opening_block_number: int
    closing_block_number: Optional[int] = None
    opening_equity_usd: float = 0.0
    closing_equity_usd: float = 0.0
    net_external_capital_usd: float = 0.0
    net_strategy_capital_usd: float = 0.0
    gross_pnl_usd: float = 0.0
    silent_mark_to_market_usd: float = 0.0
    interest_usd: float = 0.0
    trading_pnl_usd: float = 0.0
    entry_main_asset_price_usd: float = 0.0
    exit_main_asset_price_usd: Optional[float] = None
    absorbed_source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown] = Field(
        default_factory=list,
    )


class AaveSentinelUnallocatedWealthMovement(BaseModel):
    source: AaveSentinelNonTradingMovementSource
    started_at_timestamp_seconds: int
    ended_at_timestamp_seconds: int
    pnl_usd: float = 0.0
    dominant_asset_symbol: Optional[str] = None


class AaveSentinelPerformanceSummary(BaseModel):
    global_pnl_usd: float = 0.0
    realized_trading_pnl_usd: float = 0.0
    latent_trading_pnl_usd: float = 0.0
    total_trading_pnl_usd: float = 0.0
    strategy_legs_pnl_usd: float = 0.0
    unallocated_wealth_pnl_usd: float = 0.0
    pnl_reconciliation_gap_usd: float = 0.0
    cumulative_supply_interest_usd: float = 0.0
    cumulative_borrow_interest_usd: float = 0.0
    cumulative_net_interest_usd: float = 0.0
    interest_breakdowns: list[AaveSentinelReserveInterestBreakdown] = Field(default_factory=list)
    strategy_cycles: list[AaveSentinelStrategyCycleSummary] = Field(default_factory=list)
    unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement] = Field(default_factory=list)
    is_available: bool = False
    refreshed_at: Optional[datetime] = None


class AaveSentinelReserveIndexSnapshot(BaseModel):
    underlying_address: str
    liquidity_index: float
    variable_borrow_index: float


class AaveSentinelReserveIndexMemoEntry(BaseModel):
    lookup_key: AaveSentinelHistoricalAssetPriceLookupKey
    reserve_index_snapshot: AaveSentinelReserveIndexSnapshot


class AaveSentinelReserveScaledBalanceState(BaseModel):
    underlying_address: str
    scaled_supply_balance: float = 0.0
    scaled_debt_balance: float = 0.0


class AaveSentinelWalletTokenBalance(BaseModel):
    underlying_address: str
    token_amount: float = 0.0


class AaveSentinelAssetPriceUsd(BaseModel):
    underlying_address: str
    price_usd: float


class AaveSentinelPositionCheckpoint(BaseModel):
    block_number: int
    timestamp_seconds: int
    active_strategy_kinds: list[AaveSentinelStrategyKind] = Field(default_factory=list)
    short_main_asset_symbol: Optional[str] = None
    long_main_asset_symbol: Optional[str] = None
    short_leverage: float = 0.0
    long_leverage: float = 0.0
    short_strategy_equity_usd: float = 0.0
    long_strategy_equity_usd: float = 0.0
    before_transfer_short_strategy_equity_usd: float = 0.0
    before_transfer_long_strategy_equity_usd: float = 0.0
    cumulative_short_strategy_capital_usd: float = 0.0
    cumulative_long_strategy_capital_usd: float = 0.0
    total_supply_value_usd: float = 0.0
    total_debt_value_usd: float = 0.0
    equity_usd: float = 0.0
    wallet_equity_usd: float = 0.0
    cumulative_external_capital_usd: float = 0.0
    cumulative_supply_interest_usd: float = 0.0
    cumulative_borrow_interest_usd: float = 0.0
    cumulative_net_interest_usd: float = 0.0
    asset_prices_usd: list[AaveSentinelAssetPriceUsd] = Field(default_factory=list)
    scaled_balances: list[AaveSentinelReserveScaledBalanceState] = Field(default_factory=list)
    reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot] = Field(default_factory=list)
    wallet_token_balances: list[AaveSentinelWalletTokenBalance] = Field(default_factory=list)
