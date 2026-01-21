"""
Aave Sentinel Data Models
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class AaveAssetDetails:
    """Detailed breakdown of a single asset's position."""
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
    """
    Represents a normalized snapshot of the user's Aave position at a specific time.
    """
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
        """Sum of all assets found in the wallet (uninvested bag)."""
        return sum(asset.wallet_value_usd for asset in self.assets)

    @property
    def aave_net_worth_usd(self) -> float:
        """
        Net worth strictly within the Aave protocol.
        Formula: Total Collateral - Total Debt
        """
        return self.total_collateral_usd - self.total_debt_usd

    @property
    def total_strategy_equity_usd(self) -> float:
        """
        Total equity of the strategy including idle wallet cash.
        """
        return self.aave_net_worth_usd + self.total_wallet_usd

    @property
    def current_leverage(self) -> float:
        """
        Calculates the effective leverage of the Aave position.
        Formula: Total Collateral / Net Worth (Protocol Only)
        Example: Supply 1000, Debt 500 -> Equity 500 -> Leverage 2.0x
        """
        if self.aave_net_worth_usd <= 0:
            return 0.0
        return self.total_collateral_usd / self.aave_net_worth_usd

    @property
    def weighted_net_apy(self) -> float:
        """
        Calculates Net APY based on weighted averages of all positions.
        """
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
    """
    Mutable state used by the Sentinel Service to track notifications and avoid spam.
    """
    last_status_level: str = "SAFE"
    last_health_factor: Optional[float] = None
    last_total_equity_usd: Optional[float] = None
    last_notification_time: Optional[datetime] = None