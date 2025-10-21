from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_constants import JSON


# ------------------------------ Converters ------------------------------ #

def _to_optional_float(value: JSON) -> Optional[float]:
    """Convert a JSON scalar into an optional float, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _to_int_or_zero(value: JSON) -> int:
    """Convert a JSON scalar into an int, returning 0 on failure."""
    if isinstance(value, bool):  # avoid True/False being treated as 1/0
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


# ------------------------------ Core Structures ------------------------------ #

@dataclass(frozen=True)
class BaseToken:
    """Base token metadata coming from Dexscreener."""
    name: Optional[str]
    symbol: Optional[str]
    address: str

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "BaseToken":
        name = payload.get("name")
        symbol = payload.get("symbol")
        address = payload.get("address")
        return BaseToken(
            name=str(name) if isinstance(name, str) else None,
            symbol=str(symbol) if isinstance(symbol, str) else None,
            address=str(address) if isinstance(address, str) else "",
        )


@dataclass(frozen=True)
class LiquidityStats:
    """Liquidity information in USD."""
    usd: float

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "LiquidityStats":
        usd = _to_optional_float(payload.get("usd"))
        return LiquidityStats(usd=usd if usd is not None else 0.0)


@dataclass(frozen=True)
class VolumeStats:
    """Volume statistics (we currently use the 24h field)."""
    h24: float

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "VolumeStats":
        h24 = _to_optional_float(payload.get("h24"))
        return VolumeStats(h24=h24 if h24 is not None else 0.0)


@dataclass(frozen=True)
class PriceChangeStats:
    """Price change percentages over common horizons."""
    m5: Optional[float]
    h1: Optional[float]
    h24: Optional[float]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "PriceChangeStats":
        return PriceChangeStats(
            m5=_to_optional_float(payload.get("m5")),
            h1=_to_optional_float(payload.get("h1")),
            h24=_to_optional_float(payload.get("h24")),
        )


# ------------------------------ Txns Structures ------------------------------ #

@dataclass(frozen=True)
class TransactionCount:
    """
    Buy/Sell counts for a given time window.
    """
    buys: int
    sells: int

    @property
    def total(self) -> int:
        """Total number of transactions (buys + sells)."""
        return self.buys + self.sells

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "TransactionCount":
        buys = _to_int_or_zero(payload.get("buys"))
        sells = _to_int_or_zero(payload.get("sells"))
        return TransactionCount(buys=buys, sells=sells)

    def to_dict(self) -> Dict[str, int]:
        """Serialize to a plain JSON-friendly dict."""
        return {"buys": self.buys, "sells": self.sells}


@dataclass(frozen=True)
class TransactionActivity:
    """
    Aggregated transaction activity across multiple windows.

    All windows are Optional to handle partial payloads gracefully.
    """
    m5: Optional[TransactionCount]
    h1: Optional[TransactionCount]
    h6: Optional[TransactionCount]
    h24: Optional[TransactionCount]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "TransactionActivity":
        def _maybe_count(key: str) -> Optional[TransactionCount]:
            sub = payload.get(key)
            return TransactionCount.from_json(sub) if isinstance(sub, dict) else None

        return TransactionActivity(
            m5=_maybe_count("m5"),
            h1=_maybe_count("h1"),
            h6=_maybe_count("h6"),
            h24=_maybe_count("h24"),
        )

    def to_dict(self) -> Dict[str, Dict[str, int]]:
        """
        Serialize to a plain JSON-friendly dict and drop missing windows.
        """
        out: Dict[str, Dict[str, int]] = {}
        if self.m5 is not None:
            out["m5"] = self.m5.to_dict()
        if self.h1 is not None:
            out["h1"] = self.h1.to_dict()
        if self.h6 is not None:
            out["h6"] = self.h6.to_dict()
        if self.h24 is not None:
            out["h24"] = self.h24.to_dict()
        return out


# --------------------------------- Pair Model -------------------------------- #

@dataclass(frozen=True)
class DexscreenerPair:
    """
    Strongly-typed representation of a Dexscreener 'pair' document.

    Field names are pythonic; they intentionally differ from the raw JSON keys.
    """
    base_token: BaseToken
    pair_address: str
    chain_id: str
    price_usd: Optional[float]
    price_native: Optional[float]
    price_change: PriceChangeStats
    volume: VolumeStats
    liquidity: LiquidityStats
    pair_created_at: int
    txns: Optional[TransactionActivity]
    fdv: Optional[float]
    market_cap: Optional[float]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerPair":
        base = payload.get("baseToken")
        base_token = BaseToken.from_json(base) if isinstance(base, dict) else BaseToken(None, None, "")

        pair_address = payload.get("pairAddress")

        chain_raw = payload.get("chainId")
        chain_id = str(chain_raw).lower() if isinstance(chain_raw, (str, int)) else ""

        price_usd = _to_optional_float(payload.get("priceUsd"))
        price_native = _to_optional_float(payload.get("priceNative"))

        change_raw = payload.get("priceChange")
        price_change = PriceChangeStats.from_json(change_raw) if isinstance(change_raw, dict) else PriceChangeStats(
            None, None, None)

        volume_raw = payload.get("volume")
        volume = VolumeStats.from_json(volume_raw) if isinstance(volume_raw, dict) else VolumeStats(0.0)

        liquidity_raw = payload.get("liquidity")
        liquidity = LiquidityStats.from_json(liquidity_raw) if isinstance(liquidity_raw, dict) else LiquidityStats(0.0)

        pair_created_at = _to_int_or_zero(payload.get("pairCreatedAt"))

        txns_raw = payload.get("txns")
        txns = TransactionActivity.from_json(txns_raw) if isinstance(txns_raw, dict) else None

        fdv = _to_optional_float(payload.get("fdv"))
        market_cap = _to_optional_float(payload.get("marketCap"))

        return DexscreenerPair(
            base_token=base_token,
            pair_address=pair_address,
            chain_id=chain_id,
            price_usd=price_usd,
            price_native=price_native,
            price_change=price_change,
            volume=volume,
            liquidity=liquidity,
            pair_created_at=pair_created_at,
            txns=txns,
            fdv=fdv,
            market_cap=market_cap,
        )


@dataclass(frozen=True, slots=True)
class NormalizedRow:
    """
    Strongly-typed row used across the pipeline.
    Keep historical/camelCase field names to avoid touching downstream code.
    """
    name: str
    symbol: str
    tokenAddress: str
    pairAddress: str
    chain: str
    priceUsd: float
    priceNative: float
    pct5m: Optional[float]
    pct1h: Optional[float]
    pct24h: Optional[float]
    vol24h: float
    liqUsd: float
    pairCreatedAt: int
    txns: Optional[TransactionActivity] = None
    fdv: Optional[float] = None
    marketCap: Optional[float] = None

@dataclass
class TokenPrice:
    token: Token
    priceUsd: float