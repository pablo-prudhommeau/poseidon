from __future__ import annotations

import logging
from typing import Protocol

from eth_account import Account

from src.core.aavesentinel.aave_sentinel_structures import AaveSentinelConfigurationError

logger = logging.getLogger(__name__)

AAVE_SENTINEL_ENABLED_ENVIRONMENT_VARIABLE = "AAVE_SENTINEL_ENABLED"
AAVE_SENTINEL_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE = "AAVE_SENTINEL_WALLET_MNEMONIC"
ROUTESCAN_API_KEY_ENVIRONMENT_VARIABLE = "ROUTESCAN_API_KEY"

Account.enable_unaudited_hdwallet_features()


class AaveSentinelBootConfigurationSettings(Protocol):
    AAVE_SENTINEL_ENABLED: bool
    AAVE_SENTINEL_WALLET_MNEMONIC: str
    AAVE_SENTINEL_WALLET_DERIVATION_INDEX: int
    ROUTESCAN_API_KEY: str


def validate_aave_sentinel_configuration(
        configuration_settings: AaveSentinelBootConfigurationSettings,
) -> None:
    if not configuration_settings.AAVE_SENTINEL_ENABLED:
        return

    wallet_mnemonic: str = configuration_settings.AAVE_SENTINEL_WALLET_MNEMONIC.strip()
    if not wallet_mnemonic:
        raise AaveSentinelConfigurationError(
            f"{AAVE_SENTINEL_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is required when "
            f"{AAVE_SENTINEL_ENABLED_ENVIRONMENT_VARIABLE}=true",
        )

    _validate_evm_wallet_derivation(
        wallet_mnemonic=wallet_mnemonic,
        wallet_derivation_index=configuration_settings.AAVE_SENTINEL_WALLET_DERIVATION_INDEX,
    )

    routescan_api_key: str = configuration_settings.ROUTESCAN_API_KEY.strip()
    if not routescan_api_key:
        raise AaveSentinelConfigurationError(
            f"{ROUTESCAN_API_KEY_ENVIRONMENT_VARIABLE} is required when "
            f"{AAVE_SENTINEL_ENABLED_ENVIRONMENT_VARIABLE}=true",
        )

    logger.info("[CONFIGURATION][AAVESENTINEL] Sentinel configuration validated")


def _validate_evm_wallet_derivation(wallet_mnemonic: str, wallet_derivation_index: int) -> None:
    try:
        Account.from_mnemonic(
            wallet_mnemonic,
            account_path=f"m/44'/60'/0'/0/{wallet_derivation_index}",
        )
    except Exception as exception:
        raise AaveSentinelConfigurationError(
            f"{AAVE_SENTINEL_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is invalid for EVM wallet derivation — {exception}",
        ) from exception
