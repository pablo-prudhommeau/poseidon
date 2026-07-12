from __future__ import annotations

import pytest

from src.core.aavesentinel.aave_sentinel_configuration_service import validate_aave_sentinel_configuration
from src.core.aavesentinel.aave_sentinel_structures import AaveSentinelConfigurationError


class _SettingsStub:
    AAVE_SENTINEL_ENABLED: bool
    ROUTESCAN_API_KEY: str

    def __init__(
            self,
            aave_sentinel_enabled: bool,
            routescan_api_key: str,
    ) -> None:
        self.AAVE_SENTINEL_ENABLED = aave_sentinel_enabled
        self.ROUTESCAN_API_KEY = routescan_api_key


def test_validate_aave_sentinel_configuration_skips_when_sentinel_disabled() -> None:
    validate_aave_sentinel_configuration(
        _SettingsStub(
            aave_sentinel_enabled=False,
            routescan_api_key="",
        ),
    )


def test_validate_aave_sentinel_configuration_rejects_missing_routescan_api_key() -> None:
    with pytest.raises(AaveSentinelConfigurationError):
        validate_aave_sentinel_configuration(
            _SettingsStub(
                aave_sentinel_enabled=True,
                routescan_api_key="",
            ),
        )


def test_validate_aave_sentinel_configuration_accepts_enabled_sentinel_with_routescan_api_key() -> None:
    validate_aave_sentinel_configuration(
        _SettingsStub(
            aave_sentinel_enabled=True,
            routescan_api_key="rs_test_key",
        ),
    )
