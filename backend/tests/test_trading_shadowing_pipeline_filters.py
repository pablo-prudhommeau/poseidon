from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.screener.trading_screener_structures import TradingScreenerEnvelope
from src.core.trading.shadowing.trading_shadowing_pipeline import TradingShadowingPipeline
from src.core.trading.trading_configuration_service import validate_and_apply_trading_application_configuration
from src.core.trading.trading_structures import TradingCandidate, TradingDexMarketSnapshot


class _SettingsStubPumpfunAndPumpswapOnly:
    TRADING_ALLOWED_CHAINS = ["solana"]
    TRADING_SOLANA_SUPPORTED_DEX_IDS = ["pumpfun", "pumpswap"]
    TRADING_PAPER_MODE = True
    TRADING_WALLET_MNEMONIC = ""
    TRADING_WALLET_DERIVATION_INDEX = 0
    TRADING_STABLECOIN_ADDRESS_SOLANA = ""
    TRADING_STABLECOIN_ADDRESS_BSC = ""
    TRADING_STABLECOIN_ADDRESS_BASE = ""
    TRADING_STABLECOIN_ADDRESS_AVALANCHE = ""
    TRADING_STABLECOIN_ADDRESS_ROBINHOOD = ""
    LIFI_API_KEY = ""
    LIFI_INTEGRATION_ID = ""


def _build_market_snapshot() -> TradingDexMarketSnapshot:
    return TradingDexMarketSnapshot(
        price_usd=1.0,
        price_native=1.0,
        token_age_hours=2.0,
        volume_m5_usd=10000.0,
        volume_h1_usd=10000.0,
        volume_h6_usd=10000.0,
        volume_h24_usd=10000.0,
        liquidity_usd=10000.0,
        price_change_percentage_m5=1.0,
        price_change_percentage_h1=1.0,
        price_change_percentage_h6=1.0,
        price_change_percentage_h24=1.0,
        transaction_count_m5=10,
        transaction_count_h1=10,
        transaction_count_h6=10,
        transaction_count_h24=10,
        buy_to_sell_ratio=1.0,
        market_cap_usd=100000.0,
        fully_diluted_valuation_usd=100000.0,
    )


def _build_candidate(symbol: str, dex_id: str) -> TradingCandidate:
    return TradingCandidate(
        token=Token(
            symbol=symbol,
            chain=BlockchainNetwork.SOLANA,
            token_address=f"{symbol}_token",
            pair_address=f"{symbol}_pair",
            dex_id=dex_id,
        ),
        market_snapshot=_build_market_snapshot(),
        screener_envelope=TradingScreenerEnvelope(provider_id="test"),
    )


def test_filter_supported_dexes_retains_pumpfun_and_pumpswap_only() -> None:
    validate_and_apply_trading_application_configuration(_SettingsStubPumpfunAndPumpswapOnly())
    try:
        pipeline = TradingShadowingPipeline()
        candidates = [
            _build_candidate("PUMP", "pumpfun"),
            _build_candidate("SWAP", "pumpswap"),
            _build_candidate("RAY", "raydium"),
            _build_candidate("ORCA", "orca"),
        ]

        retained = pipeline._filter_supported_dexes(candidates)

        assert [candidate.token.symbol for candidate in retained] == ["PUMP", "SWAP"]
    finally:
        validate_and_apply_trading_application_configuration(settings)
