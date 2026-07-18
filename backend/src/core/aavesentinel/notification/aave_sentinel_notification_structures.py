from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AaveSentinelNotificationInventoryEntry(BaseModel):
    asset_symbol: str
    asset_amount: float
    asset_value_usd: float
    asset_annual_percentage_yield: Optional[float] = None


class AaveSentinelNotificationInventoryRow(BaseModel):
    token_symbol: str
    values_label: str
