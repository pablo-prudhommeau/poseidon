from __future__ import annotations

import logging

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_chain_capability_service import (
    TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS,
    apply_trading_allowed_blockchain_network_configuration,
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_dex_capability_service import (
    TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS,
    apply_supported_trading_solana_dex_configuration,
)
from src.core.trading.trading_structures import (
    TradingApplicationBootConfigurationSettings,
    TradingConfigurationError,
)
from src.integrations.blockchain.solana.blockchain_solana_wallet_derivation import (
    derive_solana_keypair_from_mnemonic,
)

logger = logging.getLogger(__name__)

TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE = "TRADING_ALLOWED_CHAINS"
TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE = "TRADING_SOLANA_SUPPORTED_DEX_IDS"
WALLET_MNEMONIC_ENVIRONMENT_VARIABLE = "WALLET_MNEMONIC"


def validate_and_apply_trading_application_configuration(
        configuration_settings: TradingApplicationBootConfigurationSettings,
) -> None:
    configured_chain_identifiers = _normalize_unique_identifiers(configuration_settings.TRADING_ALLOWED_CHAINS)
    configured_dex_identifiers = _normalize_unique_identifiers(
        configuration_settings.TRADING_SOLANA_SUPPORTED_DEX_IDS,
    )

    if not configured_chain_identifiers:
        raise TradingConfigurationError(
            f"{TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE} resolved to an empty list — "
            f"configure at least one application-supported blockchain",
        )
    if not configured_dex_identifiers:
        raise TradingConfigurationError(
            f"{TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE} resolved to an empty list — "
            f"configure at least one application-supported Solana dex id",
        )

    application_supported_chain_identifiers = {
        blockchain_network.value
        for blockchain_network in TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS
    }
    application_supported_dex_identifiers = set(TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS)

    effective_blockchain_networks: list[BlockchainNetwork] = []
    for chain_identifier in configured_chain_identifiers:
        if chain_identifier not in application_supported_chain_identifiers:
            application_supported_chain_labels = ", ".join(sorted(application_supported_chain_identifiers))
            raise TradingConfigurationError(
                f"{TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE} contains unsupported blockchain '{chain_identifier}' — "
                f"application-supported blockchains: {application_supported_chain_labels}",
            )
        effective_blockchain_networks.append(BlockchainNetwork(chain_identifier))

    effective_dex_identifiers: list[str] = []
    for dex_identifier in configured_dex_identifiers:
        if dex_identifier not in application_supported_dex_identifiers:
            application_supported_dex_labels = ", ".join(TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS)
            raise TradingConfigurationError(
                f"{TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE} contains unsupported dex id '{dex_identifier}' — "
                f"application-supported Solana dex ids: {application_supported_dex_labels}",
            )
        effective_dex_identifiers.append(dex_identifier)

    apply_trading_allowed_blockchain_network_configuration(effective_blockchain_networks)
    apply_supported_trading_solana_dex_configuration(effective_dex_identifiers)

    logger.info(
        "[CONFIGURATION][TRADING][APPLICATION] Effective trading capabilities — blockchains=%s solana_dex_ids=%s "
        "(application-supported blockchains=%s solana_dex_ids=%s)",
        ", ".join(blockchain_network.value for blockchain_network in effective_blockchain_networks),
        ", ".join(effective_dex_identifiers),
        ", ".join(blockchain_network.value for blockchain_network in TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS),
        ", ".join(TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS),
    )


def _normalize_unique_identifiers(raw_identifiers: list[str]) -> list[str]:
    normalized_identifiers: list[str] = []
    seen_identifiers: set[str] = set()
    for raw_identifier in raw_identifiers:
        normalized_identifier = raw_identifier.strip().lower()
        if not normalized_identifier or normalized_identifier in seen_identifiers:
            continue
        seen_identifiers.add(normalized_identifier)
        normalized_identifiers.append(normalized_identifier)
    return normalized_identifiers


def validate_live_wallet_configuration(
        configuration_settings: TradingApplicationBootConfigurationSettings,
) -> None:
    if configuration_settings.PAPER_MODE:
        return

    wallet_mnemonic = configuration_settings.WALLET_MNEMONIC.strip()
    if not wallet_mnemonic:
        raise TradingConfigurationError(
            f"{WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is required when PAPER_MODE=false",
        )

    for blockchain_network in resolve_trading_allowed_blockchain_networks():
        stablecoin_address_environment_variable = resolve_stablecoin_address_environment_variable_name(
            blockchain_network,
        )
        stablecoin_address = resolve_stablecoin_address_for_blockchain_from_settings(
            blockchain_network,
            configuration_settings,
        )
        if not stablecoin_address:
            raise TradingConfigurationError(
                f"{stablecoin_address_environment_variable} is required for enabled blockchain "
                f"'{blockchain_network.value}' when PAPER_MODE=false",
            )

        if blockchain_network == BlockchainNetwork.SOLANA:
            _validate_solana_wallet_derivation(
                wallet_mnemonic=wallet_mnemonic,
                wallet_derivation_index=configuration_settings.WALLET_DERIVATION_INDEX,
            )

    logger.info(
        "[CONFIGURATION][TRADING][WALLET] Live wallet configuration validated for blockchains=%s",
        ", ".join(blockchain_network.value for blockchain_network in resolve_trading_allowed_blockchain_networks()),
    )


def _validate_solana_wallet_derivation(wallet_mnemonic: str, wallet_derivation_index: int) -> None:
    try:
        derive_solana_keypair_from_mnemonic(
            mnemonic=wallet_mnemonic,
            wallet_derivation_index=wallet_derivation_index,
        )
    except ValueError as exception:
        raise TradingConfigurationError(
            f"{WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is invalid for Solana wallet derivation — {exception}",
        ) from exception


def resolve_stablecoin_address_environment_variable_name(blockchain_network: BlockchainNetwork) -> str:
    if blockchain_network == BlockchainNetwork.SOLANA:
        return "TRADING_STABLECOIN_ADDRESS_SOLANA"
    if blockchain_network == BlockchainNetwork.BSC:
        return "TRADING_STABLECOIN_ADDRESS_BSC"
    if blockchain_network == BlockchainNetwork.BASE:
        return "TRADING_STABLECOIN_ADDRESS_BASE"
    if blockchain_network == BlockchainNetwork.AVALANCHE:
        return "TRADING_STABLECOIN_ADDRESS_AVALANCHE"
    raise TradingConfigurationError(
        f"No stablecoin address environment variable configured for blockchain '{blockchain_network.value}'",
    )


def resolve_stablecoin_address_for_blockchain_from_settings(
        blockchain_network: BlockchainNetwork,
        configuration_settings: TradingApplicationBootConfigurationSettings,
) -> str:
    if blockchain_network == BlockchainNetwork.SOLANA:
        return configuration_settings.TRADING_STABLECOIN_ADDRESS_SOLANA.strip()
    if blockchain_network == BlockchainNetwork.BSC:
        return configuration_settings.TRADING_STABLECOIN_ADDRESS_BSC.strip()
    if blockchain_network == BlockchainNetwork.BASE:
        return configuration_settings.TRADING_STABLECOIN_ADDRESS_BASE.strip()
    if blockchain_network == BlockchainNetwork.AVALANCHE:
        return configuration_settings.TRADING_STABLECOIN_ADDRESS_AVALANCHE.strip()
    raise TradingConfigurationError(
        f"No stablecoin address configured for blockchain '{blockchain_network.value}'",
    )


def resolve_stablecoin_address_for_blockchain(blockchain_network: BlockchainNetwork) -> str:
    from src.configuration.config import settings

    return resolve_stablecoin_address_for_blockchain_from_settings(blockchain_network, settings)


def require_stablecoin_address_for_blockchain(blockchain_network: BlockchainNetwork) -> str:
    stablecoin_address = resolve_stablecoin_address_for_blockchain(blockchain_network)
    if stablecoin_address:
        return stablecoin_address

    stablecoin_address_environment_variable = resolve_stablecoin_address_environment_variable_name(blockchain_network)
    raise TradingConfigurationError(
        f"{stablecoin_address_environment_variable} is required for blockchain '{blockchain_network.value}' — "
        f"live wallet configuration must be validated at application startup",
    )
