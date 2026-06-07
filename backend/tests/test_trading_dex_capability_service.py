from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_configuration_service import validate_and_apply_trading_application_configuration
from src.core.trading.trading_dex_capability_service import (
    TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS,
    is_supported_trading_solana_dex_id,
    resolve_supported_trading_dex_identifiers,
    resolve_supported_trading_solana_dex_ids,
)


class _SettingsStub:
    TRADING_ALLOWED_CHAINS = ["solana"]
    TRADING_SOLANA_SUPPORTED_DEX_IDS = ["pumpfun"]


def test_trading_application_supported_solana_dex_ids_contains_pumpfun_and_pumpswap_only() -> None:
    assert TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS == ("pumpfun", "pumpswap")


def test_resolve_supported_trading_solana_dex_ids_uses_effective_settings_configuration() -> None:
    assert settings.TRADING_SOLANA_SUPPORTED_DEX_IDS == ["pumpfun", "pumpswap"]
    assert resolve_supported_trading_solana_dex_ids() == ["pumpfun", "pumpswap"]


def test_resolve_supported_trading_dex_identifiers_uses_effective_settings_configuration() -> None:
    assert resolve_supported_trading_dex_identifiers() == ("pumpfun", "pumpswap")


def test_is_supported_trading_solana_dex_id_respects_effective_subset() -> None:
    validate_and_apply_trading_application_configuration(_SettingsStub())

    assert is_supported_trading_solana_dex_id("pumpfun") is True
    assert is_supported_trading_solana_dex_id("pumpswap") is False
    assert is_supported_trading_solana_dex_id("raydium") is False

    validate_and_apply_trading_application_configuration(settings)
