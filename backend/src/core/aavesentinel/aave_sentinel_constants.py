from __future__ import annotations

PURE_FLOW_AMOUNT_EPSILON: float = 0.000_001

NATIVE_AVAX_ASSET_SYMBOL: str = "AVAX"
WAVAX_CONTRACT_ADDRESS: str = "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7"

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

AVALANCHE_EURC_USD_CHAINLINK_FEED_ADDRESS: str = "0x59728a5067d519b5F169c824c965eD684d5E5170"
FRANKFURTER_HISTORICAL_EXCHANGE_RATE_URL_TEMPLATE: str = (
    "https://api.frankfurter.dev/v1/{exchange_rate_date}?from=EUR&to=USD"
)
