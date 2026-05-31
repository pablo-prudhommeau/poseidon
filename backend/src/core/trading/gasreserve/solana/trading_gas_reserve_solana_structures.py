from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TradingGasReserveSolanaCostSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_open_positions: int
    token_account_rent_lamports: int
    average_swap_fee_lamports: int
    per_position_cost_lamports: int
    cycle_cost_lamports: int
