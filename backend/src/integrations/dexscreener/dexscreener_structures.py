from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from src.core.utils.date_utils import get_current_local_datetime, convert_epoch_to_local_datetime


class _DexscreenerBaseModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _convert_json_keys_to_pythonic_names(cls, payload: object) -> object:
        if isinstance(payload, dict):
            transformed_dictionary: dict[str, object] = {}
            for key, value in payload.items():
                if value == "":
                    value = None

                if key in {"m5", "h1", "h6", "h24"}:
                    pythonic_key = key
                elif key == "txns":
                    pythonic_key = "transactions"
                elif key == "fdv":
                    pythonic_key = "fully_diluted_valuation"
                elif key == "boosts" and cls.__name__ == "DexscreenerTokenInformation":
                    if isinstance(value, dict):
                        for boost_key, boost_value in value.items():
                            if boost_key == "active":
                                transformed_dictionary["boost"] = boost_value
                    continue
                else:
                    pythonic_key = re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()

                transformed_dictionary[pythonic_key] = value
            return transformed_dictionary
        return payload


class DexscreenerToken(_DexscreenerBaseModel):
    address: str
    name: str
    symbol: str

    @model_validator(mode="after")
    def _uppercase_symbol(self) -> "DexscreenerToken":
        if self.symbol:
            self.symbol = self.symbol.upper()
        return self


class DexscreenerLiquidityStatistics(_DexscreenerBaseModel):
    base: Optional[float] = None
    quote: Optional[float] = None
    usd: Optional[float] = None


class DexscreenerVolumeStatistics(_DexscreenerBaseModel):
    m5: Optional[float] = None
    h1: Optional[float] = None
    h6: Optional[float] = None
    h24: Optional[float] = None


class DexscreenerPriceChangeStatistics(_DexscreenerBaseModel):
    m5: Optional[float] = None
    h1: Optional[float] = None
    h6: Optional[float] = None
    h24: Optional[float] = None


class DexscreenerTransactionCount(_DexscreenerBaseModel):
    buys: int
    sells: int

    @property
    def total_transactions(self) -> int:
        return self.buys + self.sells


class DexscreenerTransactionActivity(_DexscreenerBaseModel):
    m5: Optional[DexscreenerTransactionCount] = None
    h1: Optional[DexscreenerTransactionCount] = None
    h6: Optional[DexscreenerTransactionCount] = None
    h24: Optional[DexscreenerTransactionCount] = None


class DexscreenerWebsite(_DexscreenerBaseModel):
    label: str
    url: str


class DexscreenerSocial(_DexscreenerBaseModel):
    type: str
    url: str


class DexscreenerInformation(_DexscreenerBaseModel):
    image_url: Optional[str] = None
    header: Optional[str] = None
    open_graph: Optional[str] = None
    websites: list[DexscreenerWebsite] = Field(default_factory=list)
    socials: list[DexscreenerSocial] = Field(default_factory=list)
    boosts: list[float] = Field(default_factory=list)


class DexscreenerTokenInformation(_DexscreenerBaseModel):
    base_token: DexscreenerToken
    quote_token: DexscreenerToken
    pair_address: str
    chain_id: str
    dex_id: str
    price_usd: Optional[float] = None
    price_native: Optional[float] = None
    price_change: Optional[DexscreenerPriceChangeStatistics] = None
    volume: Optional[DexscreenerVolumeStatistics] = None
    liquidity: Optional[DexscreenerLiquidityStatistics] = None
    pair_created_at: Optional[int] = None
    transactions: Optional[DexscreenerTransactionActivity] = None
    fully_diluted_valuation: Optional[float] = None
    market_cap: Optional[float] = None
    info: Optional[DexscreenerInformation] = None
    url: Optional[str] = None
    boost: Optional[float] = None

    retrieval_date: datetime = Field(default_factory=get_current_local_datetime)

    @property
    def age_hours(self) -> float:
        if self.pair_created_at is not None and self.pair_created_at > 0:
            created_at_datetime = convert_epoch_to_local_datetime(self.pair_created_at)
            age_delta = self.retrieval_date - created_at_datetime
            return max(0.0, age_delta.total_seconds() / 3600.0)
        return 0.0
