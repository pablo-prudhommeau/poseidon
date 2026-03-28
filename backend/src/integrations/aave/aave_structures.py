from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


@dataclass(frozen=True)
class AaveAssetDetails:
    symbol: str
    underlying_address: str
    supply_amount: float
    debt_amount: float
    wallet_amount: float
    supply_value_usd: float
    debt_value_usd: float
    wallet_value_usd: float
    supply_apy: float
    borrow_apy: float


@dataclass(frozen=True)
class AavePositionSnapshot:
    health_factor: float
    total_collateral_usd: float
    total_debt_usd: float

    strategy: str = "NEUTRAL"
    main_asset_symbol: Optional[str] = None
    main_asset_price: Optional[float] = None
    liquidation_price_usd: Optional[float] = None

    assets: List[AaveAssetDetails] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now().astimezone())

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
        total_supply_value = sum(asset.supply_value_usd for asset in self.assets)
        total_debt_value = sum(asset.debt_value_usd for asset in self.assets)

        if total_supply_value <= 0 and total_debt_value <= 0:
            return 0.0

        income = sum(asset.supply_value_usd * asset.supply_apy for asset in self.assets)
        cost = sum(asset.debt_value_usd * asset.borrow_apy for asset in self.assets)

        equity = total_supply_value - total_debt_value

        if equity <= 0:
            return 0.0

        return (income - cost) / equity


@dataclass
class SentinelState:
    last_status_level: str = "SAFE"
    last_health_factor: Optional[float] = None
    last_total_equity_usd: Optional[float] = None
    last_notification_time: Optional[datetime] = None


class AaveLiveMetrics(BaseModel):
    supply_apy: float
    asset_out_price_usd: float
