from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.utils.date_utils import get_current_local_datetime


class AaveSentinelStrategyDirection(str, Enum):
    NEUTRAL = "NEUTRAL"
    LONG = "LONG"
    SHORT = "SHORT"


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


class AaveSentinelPositionSnapshot(BaseModel):
    health_factor: float
    total_collateral_usd: float
    total_debt_usd: float
    strategy_direction: AaveSentinelStrategyDirection = AaveSentinelStrategyDirection.NEUTRAL
    main_asset_symbol: Optional[str] = None
    main_asset_price_usd: Optional[float] = None
    liquidation_price_usd: Optional[float] = None
    assets: list[AaveSentinelAssetSnapshot] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=get_current_local_datetime)


class AaveSentinelStrategySnapshotResolution(BaseModel):
    strategy_direction: AaveSentinelStrategyDirection = AaveSentinelStrategyDirection.NEUTRAL
    main_asset_symbol: Optional[str] = None
    main_asset_price_usd: Optional[float] = None
    liquidation_price_usd: Optional[float] = None


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
    erc20_transfer_flows: list[AaveSentinelErc20TransferFlowRecord] = Field(default_factory=list)


class AaveSentinelUniversalLedger(BaseModel):
    entries: list[AaveSentinelUniversalLedgerEntry] = Field(default_factory=list)


class AaveSentinelEuroConversionContext(BaseModel):
    block_number: int
    timestamp_seconds: int


class AaveSentinelFrankfurterExchangeRates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    USD: Optional[float] = None
    EUR: Optional[float] = None


class AaveSentinelFrankfurterExchangeRateResponse(BaseModel):
    rates: AaveSentinelFrankfurterExchangeRates


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
