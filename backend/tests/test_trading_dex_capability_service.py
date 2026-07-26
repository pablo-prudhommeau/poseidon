from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_configuration_service import validate_and_apply_trading_application_configuration
from src.core.trading.trading_dex_capability_service import (
    TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS,
    is_supported_trading_solana_dex_id,
    resolve_supported_trading_dex_identifiers,
    resolve_supported_trading_solana_dex_ids,
)


class _SettingsStubPumpfunOnly:
    TRADING_ALLOWED_CHAINS = ["solana"]
    TRADING_SOLANA_SUPPORTED_DEX_IDS = ["pumpfun"]
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


def test_trading_application_supported_solana_dex_ids_lists_parser_backed_dexes() -> None:
    assert "pumpfun" in TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS
    assert "pumpswap" in TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS
    assert "jupiter" not in TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS
    assert "*" not in TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS
    assert "moonshot" not in TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS


def test_resolve_supported_trading_solana_dex_ids_uses_effective_settings_configuration() -> None:
    expected_default_dex_ids = [
        "pumpfun",
        "pumpswap",
        "raydium",
        "raydium-cpmm",
        "raydium-clmm",
        "orca",
        "meteora",
    ]
    assert settings.TRADING_SOLANA_SUPPORTED_DEX_IDS == expected_default_dex_ids
    assert resolve_supported_trading_solana_dex_ids() == expected_default_dex_ids


def test_resolve_supported_trading_dex_identifiers_uses_effective_settings_configuration() -> None:
    assert resolve_supported_trading_dex_identifiers() == (
        "pumpfun",
        "pumpswap",
        "raydium",
        "raydium-cpmm",
        "raydium-clmm",
        "orca",
        "meteora",
    )


def test_is_supported_trading_solana_dex_id_respects_effective_subset() -> None:
    validate_and_apply_trading_application_configuration(_SettingsStubPumpfunOnly())

    assert is_supported_trading_solana_dex_id("pumpfun") is True
    assert is_supported_trading_solana_dex_id("pumpswap") is False
    assert is_supported_trading_solana_dex_id("raydium") is False

    validate_and_apply_trading_application_configuration(settings)
