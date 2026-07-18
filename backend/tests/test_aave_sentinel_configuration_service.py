from __future__ import annotations

import pytest

from src.core.aavesentinel.aave_sentinel_configuration_service import validate_aave_sentinel_configuration
from src.core.aavesentinel.aave_sentinel_structures import AaveSentinelConfigurationError

_VALID_TEST_WALLET_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)


class _SettingsStub:
    AAVE_SENTINEL_ENABLED: bool
    AAVE_SENTINEL_WALLET_MNEMONIC: str
    AAVE_SENTINEL_WALLET_DERIVATION_INDEX: int
    ROUTESCAN_API_KEY: str

    def __init__(
            self,
            aave_sentinel_enabled: bool,
            routescan_api_key: str,
            wallet_mnemonic: str = "",
            wallet_derivation_index: int = 0,
    ) -> None:
        self.AAVE_SENTINEL_ENABLED = aave_sentinel_enabled
        self.AAVE_SENTINEL_WALLET_MNEMONIC = wallet_mnemonic
        self.AAVE_SENTINEL_WALLET_DERIVATION_INDEX = wallet_derivation_index
        self.ROUTESCAN_API_KEY = routescan_api_key


def test_validate_aave_sentinel_configuration_skips_when_sentinel_disabled() -> None:
    validate_aave_sentinel_configuration(
        _SettingsStub(
            aave_sentinel_enabled=False,
            routescan_api_key="",
            wallet_mnemonic="",
        ),
    )


def test_validate_aave_sentinel_configuration_rejects_missing_wallet_mnemonic() -> None:
    with pytest.raises(AaveSentinelConfigurationError):
        validate_aave_sentinel_configuration(
            _SettingsStub(
                aave_sentinel_enabled=True,
                routescan_api_key="rs_test_key",
                wallet_mnemonic="",
            ),
        )


def test_validate_aave_sentinel_configuration_rejects_invalid_wallet_mnemonic() -> None:
    with pytest.raises(AaveSentinelConfigurationError):
        validate_aave_sentinel_configuration(
            _SettingsStub(
                aave_sentinel_enabled=True,
                routescan_api_key="rs_test_key",
                wallet_mnemonic="not a valid mnemonic phrase at all",
            ),
        )


def test_validate_aave_sentinel_configuration_rejects_missing_routescan_api_key() -> None:
    with pytest.raises(AaveSentinelConfigurationError):
        validate_aave_sentinel_configuration(
            _SettingsStub(
                aave_sentinel_enabled=True,
                routescan_api_key="",
                wallet_mnemonic=_VALID_TEST_WALLET_MNEMONIC,
            ),
        )


def test_validate_aave_sentinel_configuration_accepts_enabled_sentinel_with_required_settings() -> None:
    validate_aave_sentinel_configuration(
        _SettingsStub(
            aave_sentinel_enabled=True,
            routescan_api_key="rs_test_key",
            wallet_mnemonic=_VALID_TEST_WALLET_MNEMONIC,
        ),
    )
