from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional, List

from src.core.utils.date_utils import timezone_now, epoch_to_local_datetime
from src.integrations.dexscreener.dexscreener_constants import JSON


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
    if isinstance(value, bool):
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


@dataclass(frozen=True)
class DexscreenerToken:
    address: str
    name: str
    symbol: str

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerToken":
        address = payload.get("address")
        name = payload.get("name")
        symbol = payload.get("symbol")
        return DexscreenerToken(
            address=str(address) if address is not None else "",
            name=str(name) if name is not None else "",
            symbol=str(symbol).upper() if symbol is not None else ""
        )


@dataclass(frozen=True)
class DexscreenerLiquidityStats:
    base: Optional[float]
    quote: Optional[float]
    usd: Optional[float]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerLiquidityStats":
        return DexscreenerLiquidityStats(
            base=_to_optional_float(payload.get("base")),
            quote=_to_optional_float(payload.get("quote")),
            usd=_to_optional_float(payload.get("usd"))
        )


@dataclass(frozen=True)
class DexscreenerVolumeStats:
    m5: Optional[float]
    h1: Optional[float]
    h6: Optional[float]
    h24: Optional[float]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerVolumeStats":
        return DexscreenerVolumeStats(
            m5=_to_optional_float(payload.get("m5")),
            h1=_to_optional_float(payload.get("h1")),
            h6=_to_optional_float(payload.get("h6")),
            h24=_to_optional_float(payload.get("h24"))
        )


@dataclass(frozen=True)
class DexscreenerPriceChangeStats:
    m5: Optional[float]
    h1: Optional[float]
    h6: Optional[float]
    h24: Optional[float]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerPriceChangeStats":
        return DexscreenerPriceChangeStats(
            m5=_to_optional_float(payload.get("m5")),
            h1=_to_optional_float(payload.get("h1")),
            h6=_to_optional_float(payload.get("h6")),
            h24=_to_optional_float(payload.get("h24"))
        )


@dataclass(frozen=True)
class DexscreenerTransactionCount:
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
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerTransactionCount":
        buys = _to_int_or_zero(payload.get("buys"))
        sells = _to_int_or_zero(payload.get("sells"))
        return DexscreenerTransactionCount(buys=buys, sells=sells)

    def to_dict(self) -> Dict[str, int]:
        """Serialize to a plain JSON-friendly dict."""
        return {"buys": self.buys, "sells": self.sells}


@dataclass(frozen=True)
class DexscreenerTransactionActivity:
    """
    Aggregated transaction activity across multiple windows.

    All windows are Optional to handle partial payloads gracefully.
    """
    m5: Optional[DexscreenerTransactionCount]
    h1: Optional[DexscreenerTransactionCount]
    h6: Optional[DexscreenerTransactionCount]
    h24: Optional[DexscreenerTransactionCount]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerTransactionActivity":
        def _maybe_count(key: str) -> Optional[DexscreenerTransactionCount]:
            sub = payload.get(key)
            return DexscreenerTransactionCount.from_json(sub) if isinstance(sub, dict) else None

        return DexscreenerTransactionActivity(
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


@dataclass(frozen=True)
class DexscreenerInfo:
    imageUrl: str
    header: str
    openGraph: str
    websites: List[DexscreenerWebsite]
    socials: List[DexscreenerSocial]
    boosts: List[float]

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerInfo":
        image_url = payload.get("imageUrl") or ""
        header = payload.get("header") or ""
        open_graph = payload.get("openGraph") or ""

        websites_raw = payload.get("websites") or []
        websites: List[DexscreenerWebsite] = []
        if isinstance(websites_raw, list):
            for item in websites_raw:
                if isinstance(item, dict):
                    label = item.get("label") or ""
                    url = item.get("url") or ""
                    websites.append(DexscreenerWebsite(label=str(label), url=str(url)))

        socials_raw = payload.get("socials") or []
        socials: List[DexscreenerSocial] = []
        if isinstance(socials_raw, list):
            for item in socials_raw:
                if isinstance(item, dict):
                    type_ = item.get("type") or ""
                    url = item.get("url") or ""
                    socials.append(DexscreenerSocial(type=str(type_), url=str(url)))

        boosts_raw = payload.get("boosts") or []
        boosts: List[float] = []
        if isinstance(boosts_raw, list):
            for item in boosts_raw:
                boost_value = _to_optional_float(item)
                if boost_value is not None:
                    boosts.append(boost_value)

        return DexscreenerInfo(
            imageUrl=str(image_url),
            header=str(header),
            openGraph=str(open_graph),
            websites=websites,
            socials=socials,
            boosts=boosts
        )


@dataclass(frozen=True)
class DexscreenerWebsite:
    label: str
    url: str


@dataclass(frozen=True)
class DexscreenerSocial:
    type: str
    url: str


@dataclass(frozen=True)
class DexscreenerTokenInformation:
    """
    Strongly-typed representation of a Dexscreener 'pair' document.

    Field names are pythonic; they intentionally differ from the raw JSON keys.
    """
    base_token: DexscreenerToken
    quote_token: DexscreenerToken
    pair_address: str
    chain_id: str
    dex_id: str
    price_usd: Optional[float]
    price_native: Optional[float]
    price_change: DexscreenerPriceChangeStats
    volume: DexscreenerVolumeStats
    liquidity: DexscreenerLiquidityStats
    pair_created_at: int
    txns: Optional[DexscreenerTransactionActivity]
    fully_diluted_valuation: Optional[float]
    market_cap: Optional[float]
    retrieval_date: datetime
    age_hours: Optional[float]
    info: DexscreenerInfo
    url: str
    boost: float

    def to_dict(self) -> Dict[str, JSON]:
        payload = asdict(self)
        payload["retrieval_date"] = self.retrieval_date.isoformat()
        return payload

    @staticmethod
    def from_json(payload: Dict[str, JSON]) -> "DexscreenerTokenInformation":
        base = payload.get("baseToken")
        base_token = DexscreenerToken.from_json(base) \
            if isinstance(base, dict) else DexscreenerToken(None, None, "")
        quote = payload.get("quoteToken")
        quote_token = DexscreenerToken.from_json(quote) \
            if isinstance(quote, dict) else DexscreenerToken(None, None, "")
        pair_address = payload.get("pairAddress")
        chain_raw = payload.get("chainId")
        chain_id = str(chain_raw).lower() if isinstance(chain_raw, (str, int)) else ""
        dex_raw = payload.get("dexId")
        dex_id = str(dex_raw).lower() if isinstance(dex_raw, (str, int)) else ""
        price_usd = _to_optional_float(payload.get("priceUsd"))
        price_native = _to_optional_float(payload.get("priceNative"))
        change_raw = payload.get("priceChange")
        price_change = DexscreenerPriceChangeStats.from_json(change_raw) \
            if isinstance(change_raw, dict) else DexscreenerPriceChangeStats(None, None, None)
        volume_raw = payload.get("volume")
        volume = DexscreenerVolumeStats.from_json(volume_raw) \
            if isinstance(volume_raw, dict) else DexscreenerVolumeStats(0.0, 0.0, 0.0, 0.0)
        liquidity_raw = payload.get("liquidity")
        liquidity = DexscreenerLiquidityStats.from_json(liquidity_raw) \
            if isinstance(liquidity_raw, dict) else DexscreenerLiquidityStats(0.0, 0.0, 0.0)
        pair_created_at = _to_int_or_zero(payload.get("pairCreatedAt"))
        txns_raw = payload.get("txns")
        txns = DexscreenerTransactionActivity.from_json(txns_raw) if isinstance(txns_raw, dict) else None
        fdv = _to_optional_float(payload.get("fdv"))
        market_cap = _to_optional_float(payload.get("marketCap"))
        retrieval_date = timezone_now()
        age_hours = 0
        if pair_created_at > 0:
            created_at_dt = epoch_to_local_datetime(pair_created_at)
            age_delta = retrieval_date - created_at_dt
            age_hours = age_delta.total_seconds() / 3600.0
        info = DexscreenerInfo.from_json(payload.get("info") or {})
        url = payload.get("url")
        boost = payload.get("boosts").get("active") if isinstance(payload.get("boosts"), dict) else None
        return DexscreenerTokenInformation(
            base_token=base_token,
            quote_token=quote_token,
            pair_address=pair_address,
            chain_id=chain_id,
            dex_id=dex_id,
            price_usd=price_usd,
            price_native=price_native,
            price_change=price_change,
            volume=volume,
            liquidity=liquidity,
            pair_created_at=pair_created_at,
            txns=txns,
            fully_diluted_valuation=fdv,
            market_cap=market_cap,
            retrieval_date=retrieval_date,
            age_hours=age_hours,
            info=info,
            url=url,
            boost=boost
        )
