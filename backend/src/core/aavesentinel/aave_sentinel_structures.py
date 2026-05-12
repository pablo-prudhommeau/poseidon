from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

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


class AaveSentinelRescueExecutionStatus(str, Enum):
    SKIPPED = "SKIPPED"
    SIMULATED = "SIMULATED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


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

    @property
    def total_wallet_usd(self) -> float:
        return sum(asset.wallet_value_usd for asset in self.assets)

    @property
    def aave_net_worth_usd(self) -> float:
        return self.total_collateral_usd - self.total_debt_usd

    @property
    def total_strategy_equity_usd(self) -> float:
        return self.aave_net_worth_usd + self.total_wallet_usd

    @property
    def current_leverage(self) -> float:
        if self.aave_net_worth_usd <= 0:
            return 0.0
        return self.total_collateral_usd / self.aave_net_worth_usd

    @property
    def weighted_net_apy(self) -> float:
        total_supply_value_usd = sum(asset.supply_value_usd for asset in self.assets)
        total_debt_value_usd = sum(asset.debt_value_usd for asset in self.assets)

        if total_supply_value_usd <= 0 and total_debt_value_usd <= 0:
            return 0.0

        total_supply_income_usd = sum(
            asset.supply_value_usd * asset.supply_annual_percentage_yield
            for asset in self.assets
        )
        total_borrow_cost_usd = sum(
            asset.debt_value_usd * asset.borrow_annual_percentage_yield
            for asset in self.assets
        )
        current_equity_usd = total_supply_value_usd - total_debt_value_usd

        if current_equity_usd <= 0:
            return 0.0

        return (total_supply_income_usd - total_borrow_cost_usd) / current_equity_usd


class AaveSentinelState(BaseModel):
    last_risk_status: AaveSentinelRiskStatus = AaveSentinelRiskStatus.OPTIMAL
    last_health_factor: Optional[float] = None
    last_total_equity_usd: Optional[float] = None
    last_notification_time: Optional[datetime] = None


class AaveSentinelRescueExecutionResult(BaseModel):
    status: AaveSentinelRescueExecutionStatus
    message: str
    amount_usdc: Optional[float] = None
    transaction_hash: Optional[str] = None
