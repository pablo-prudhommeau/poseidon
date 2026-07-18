from __future__ import annotations

from typing import Optional

EURO_STABLECOIN_SYMBOLS: frozenset[str] = frozenset({"EURC", "EUROC"})
USD_FIAT_STABLECOIN_SYMBOLS: frozenset[str] = frozenset({
    "USDC",
    "USDT",
    "DAI",
    "GHO",
    "FRAX",
    "LUSD",
    "MIM",
    "TUSD",
    "USDD",
    "SUSD",
    "USDC.E",
})

_USD_CURRENCY_GLYPH: str = "$"
_EUR_CURRENCY_GLYPH: str = "€"
_AVAX_CURRENCY_GLYPH: str = "Ⓐ"
_BTC_CURRENCY_GLYPH: str = "₿"
_ETH_CURRENCY_GLYPH: str = "Ξ"
_SOL_CURRENCY_GLYPH: str = "◎"
_LINK_CURRENCY_GLYPH: str = "⬡"
_AAVE_CURRENCY_GLYPH: str = "Ⓐ"

_ASSET_CURRENCY_GLYPH_BY_NORMALIZED_SYMBOL: dict[str, str] = {
    "AVAX": _AVAX_CURRENCY_GLYPH,
    "WAVAX": _AVAX_CURRENCY_GLYPH,
    "BTC": _BTC_CURRENCY_GLYPH,
    "BTC.B": _BTC_CURRENCY_GLYPH,
    "WBTC": _BTC_CURRENCY_GLYPH,
    "WBTC.E": _BTC_CURRENCY_GLYPH,
    "ETH": _ETH_CURRENCY_GLYPH,
    "WETH": _ETH_CURRENCY_GLYPH,
    "WETH.E": _ETH_CURRENCY_GLYPH,
    "SOL": _SOL_CURRENCY_GLYPH,
    "WSOL": _SOL_CURRENCY_GLYPH,
    "LINK": _LINK_CURRENCY_GLYPH,
    "AAVE": _AAVE_CURRENCY_GLYPH,
}


def _normalize_asset_symbol(asset_symbol: str) -> str:
    return asset_symbol.strip().upper()


def get_currency_symbol(asset_symbol: str) -> str:
    if not asset_symbol:
        return ""

    normalized_asset_symbol: str = _normalize_asset_symbol(asset_symbol)

    if normalized_asset_symbol in USD_FIAT_STABLECOIN_SYMBOLS:
        return _USD_CURRENCY_GLYPH
    if normalized_asset_symbol in EURO_STABLECOIN_SYMBOLS:
        return _EUR_CURRENCY_GLYPH

    mapped_currency_glyph: Optional[str] = _ASSET_CURRENCY_GLYPH_BY_NORMALIZED_SYMBOL.get(
        normalized_asset_symbol
    )
    if mapped_currency_glyph is not None:
        return mapped_currency_glyph

    if "USD" in normalized_asset_symbol or normalized_asset_symbol.endswith("DAI"):
        return _USD_CURRENCY_GLYPH
    if "EUR" in normalized_asset_symbol:
        return _EUR_CURRENCY_GLYPH
    if "BTC" in normalized_asset_symbol:
        return _BTC_CURRENCY_GLYPH
    if "ETH" in normalized_asset_symbol:
        return _ETH_CURRENCY_GLYPH
    if "AVAX" in normalized_asset_symbol:
        return _AVAX_CURRENCY_GLYPH
    if "SOL" in normalized_asset_symbol:
        return _SOL_CURRENCY_GLYPH
    if "LINK" in normalized_asset_symbol:
        return _LINK_CURRENCY_GLYPH
    if "AAVE" in normalized_asset_symbol:
        return _AAVE_CURRENCY_GLYPH

    return asset_symbol
