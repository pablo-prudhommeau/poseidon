from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.core.structures.structures import BlockchainNetwork


class TradingWalletMaintenanceOperationStatus(str, Enum):
    SKIPPED = "skipped"
    SUCCESS = "success"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class TradingNativeGasThresholdSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blockchain_network: BlockchainNetwork
    threshold_raw_lamports: int
    target_raw_lamports: int
    native_token_symbol: str


class TradingWalletMaintenanceChainGasResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blockchain_network: BlockchainNetwork
    status: TradingWalletMaintenanceOperationStatus
    reason: Optional[str] = None
    native_balance_before_lamports: Optional[int] = None
    native_balance_after_lamports: Optional[int] = None
    refill_transaction_signature: Optional[str] = None
    stablecoin_spent_raw: Optional[int] = None


class TradingWalletMaintenanceChainReclaimResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blockchain_network: BlockchainNetwork
    status: TradingWalletMaintenanceOperationStatus
    reason: Optional[str] = None
    reclaimed_account_count: int = 0
    reclaimed_lamports: int = 0
    transaction_signatures: list[str] = []


class TradingWalletMaintenanceCycleSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gas_results: list[TradingWalletMaintenanceChainGasResult]
    reclaim_results: list[TradingWalletMaintenanceChainReclaimResult]
