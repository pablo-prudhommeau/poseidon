from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class FrankfurterExchangeRates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    USD: Optional[float] = None
    EUR: Optional[float] = None


class FrankfurterExchangeRateResponse(BaseModel):
    rates: FrankfurterExchangeRates
