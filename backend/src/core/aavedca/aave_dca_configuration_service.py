from __future__ import annotations

import logging

from eth_account import Account

from src.configuration.config import Settings
from src.core.aavedca.aave_dca_structures import AaveDcaConfigurationError

logger = logging.getLogger(__name__)

AAVE_DCA_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE = "AAVE_DCA_WALLET_MNEMONIC"
AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE = "AAVE_DCA_PAPER_MODE"
RPC_PREMIUM_URL_AVALANCHE_ENVIRONMENT_VARIABLE = "RPC_PREMIUM_URL_AVALANCHE"
AAVE_POOL_V3_ADDRESS_ENVIRONMENT_VARIABLE = "AAVE_POOL_V3_ADDRESS"
AAVE_USDC_ADDRESS_ENVIRONMENT_VARIABLE = "AAVE_USDC_ADDRESS"
AAVE_BTCB_ADDRESS_ENVIRONMENT_VARIABLE = "AAVE_BTCB_ADDRESS"
AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT_ENVIRONMENT_VARIABLE = "AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT"
AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX_ENVIRONMENT_VARIABLE = "AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX"
LIFI_API_KEY_ENVIRONMENT_VARIABLE = "LIFI_API_KEY"
LIFI_INTEGRATION_ID_ENVIRONMENT_VARIABLE = "LIFI_INTEGRATION_ID"

Account.enable_unaudited_hdwallet_features()


def validate_aave_dca_live_wallet_configuration(configuration_settings: Settings) -> None:
    if not configuration_settings.AAVE_DCA_ENABLED:
        return

    if configuration_settings.AAVE_DCA_PAPER_MODE:
        return

    wallet_mnemonic: str = configuration_settings.AAVE_DCA_WALLET_MNEMONIC.strip()
    if not wallet_mnemonic:
        raise AaveDcaConfigurationError(
            f"{AAVE_DCA_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is required when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    _validate_evm_wallet_derivation(
        wallet_mnemonic=wallet_mnemonic,
        wallet_derivation_index=configuration_settings.AAVE_DCA_WALLET_DERIVATION_INDEX,
    )

    if not configuration_settings.RPC_PREMIUM_URL_AVALANCHE.strip():
        raise AaveDcaConfigurationError(
            f"{RPC_PREMIUM_URL_AVALANCHE_ENVIRONMENT_VARIABLE} is required when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    if not configuration_settings.AAVE_POOL_V3_ADDRESS.strip():
        raise AaveDcaConfigurationError(
            f"{AAVE_POOL_V3_ADDRESS_ENVIRONMENT_VARIABLE} is required when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    if not configuration_settings.AAVE_USDC_ADDRESS.strip():
        raise AaveDcaConfigurationError(
            f"{AAVE_USDC_ADDRESS_ENVIRONMENT_VARIABLE} is required when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    if not configuration_settings.AAVE_BTCB_ADDRESS.strip():
        raise AaveDcaConfigurationError(
            f"{AAVE_BTCB_ADDRESS_ENVIRONMENT_VARIABLE} is required when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    if configuration_settings.AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT <= 0:
        raise AaveDcaConfigurationError(
            f"{AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT_ENVIRONMENT_VARIABLE} must be strictly positive when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    if configuration_settings.AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX <= 0:
        raise AaveDcaConfigurationError(
            f"{AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX_ENVIRONMENT_VARIABLE} must be strictly positive when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    if not configuration_settings.LIFI_API_KEY.strip():
        raise AaveDcaConfigurationError(
            f"{LIFI_API_KEY_ENVIRONMENT_VARIABLE} is required when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    if not configuration_settings.LIFI_INTEGRATION_ID.strip():
        raise AaveDcaConfigurationError(
            f"{LIFI_INTEGRATION_ID_ENVIRONMENT_VARIABLE} is required when {AAVE_DCA_PAPER_MODE_ENVIRONMENT_VARIABLE}=false",
        )

    logger.info("[CONFIGURATION][AAVEDCA][WALLET] Live wallet configuration validated for Avalanche Aave DCA execution")


def _validate_evm_wallet_derivation(wallet_mnemonic: str, wallet_derivation_index: int) -> None:
    try:
        Account.from_mnemonic(
            wallet_mnemonic,
            account_path=f"m/44'/60'/0'/0/{wallet_derivation_index}",
        )
    except ValueError as exception:
        raise AaveDcaConfigurationError(
            f"{AAVE_DCA_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is invalid for EVM wallet derivation — {exception}",
        ) from exception
