from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TradingWalletMaintenanceSolanaGasBudgetSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_open_positions: int
    token_account_rent_lamports: int
    average_swap_fee_lamports: int
    cycle_cost_lamports: int
    refill_threshold_lamports: int
    refill_target_lamports: int


class TradingWalletMaintenanceSolanaReclaimableTokenAccount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token_account_address: str
    token_mint_address: str
    owner_program_id: str
    last_activity_timestamp_iso: str
