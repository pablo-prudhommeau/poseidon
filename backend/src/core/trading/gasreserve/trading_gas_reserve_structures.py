from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.solana.solana_structures import SolanaTokenAccountRentBreakdown


class GasRefillLockedStablecoinSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blockchain_network: BlockchainNetwork
    gas_refill_locked_stablecoin_usd: float


class GasRefillLockedBreakdownSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    per_position_cycle_cost_usd: float
    per_position_cycle_cost_native_raw: float
    max_open_positions: int
    portfolio_cycle_cost_usd: float
    portfolio_cycle_cost_native_raw: float
    refill_target_cycle_count: int
    refill_target_budget_usd: float
    refill_target_budget_native_raw: float
    native_gas_balance_usd: float
    native_gas_balance_raw: float
    refill_trigger_cycle_count: int
    refill_trigger_threshold_usd: float
    refill_trigger_threshold_native_raw: float
    locked_stablecoin_usd: float


class WalletAuxiliaryAssetsSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blockchain_network: BlockchainNetwork
    native_token_balance_usd: float
    gas_refill_locked_stablecoin_usd: float
    recoverable_wallet_capital_usd: float

    @property
    def total_wallet_auxiliary_assets_usd(self) -> float:
        return (
            self.native_token_balance_usd
            + self.gas_refill_locked_stablecoin_usd
            + self.recoverable_wallet_capital_usd
        )


class BlockchainCashBalanceGasReserveEnrichment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gas_refill_locked_stablecoin_usd: float
    gas_refill_locked_breakdown: Optional[GasRefillLockedBreakdownSnapshot] = None
    solana_token_account_rent: Optional[SolanaTokenAccountRentBreakdown] = None

    @staticmethod
    def empty() -> BlockchainCashBalanceGasReserveEnrichment:
        return BlockchainCashBalanceGasReserveEnrichment(
            gas_refill_locked_stablecoin_usd=0.0,
        )
