from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_chain_capability_service import (
    TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS,
    apply_trading_capabilities_snapshot,
    is_trading_evm_blockchain_network,
    resolve_trading_allowed_blockchain_networks,
    resolve_trading_capabilities_snapshot,
)
from src.core.trading.trading_dex_capability_service import (
    TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS,
)
from src.core.trading.trading_structures import (
    TradingApplicationBootConfigurationSettings,
    TradingCapabilitiesSnapshot,
    TradingConfigurationError,
    TradingStablecoinAddressBinding,
)
from src.integrations.blockchain.evm.blockchain_evm_structures import (
    EVM_CHAIN_PRICE_METADATA_REGISTRY,
)
from src.integrations.blockchain.solana.blockchain_solana_wallet_derivation import (
    derive_solana_keypair_from_mnemonic,
)
from src.integrations.blockchain.solana.solana_dex_pool_parser_registry import (
    has_onchain_pool_price_parser_for_dex_id,
    resolve_onchain_pool_price_parser_dex_ids,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE = "TRADING_ALLOWED_CHAINS"
TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE = "TRADING_SOLANA_SUPPORTED_DEX_IDS"
TRADING_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE = "TRADING_WALLET_MNEMONIC"
LIFI_API_KEY_ENVIRONMENT_VARIABLE = "LIFI_API_KEY"
LIFI_INTEGRATION_ID_ENVIRONMENT_VARIABLE = "LIFI_INTEGRATION_ID"


def validate_and_apply_trading_application_configuration(
        configuration_settings: TradingApplicationBootConfigurationSettings,
) -> None:
    from src.configuration.config import MAX_TRADING_ALLOWED_CHAIN_COUNT

    configured_chain_identifiers = _normalize_unique_identifiers(configuration_settings.TRADING_ALLOWED_CHAINS)
    configured_dex_identifiers = _normalize_unique_identifiers(
        configuration_settings.TRADING_SOLANA_SUPPORTED_DEX_IDS,
    )

    if not configured_chain_identifiers:
        raise TradingConfigurationError(
            f"{TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE} resolved to an empty list — "
            f"configure at least one application-supported blockchain",
        )
    if len(configured_chain_identifiers) > MAX_TRADING_ALLOWED_CHAIN_COUNT:
        raise TradingConfigurationError(
            f"{TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE} contains {len(configured_chain_identifiers)} blockchains — "
            f"maximum allowed is {MAX_TRADING_ALLOWED_CHAIN_COUNT}",
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
        if not has_onchain_pool_price_parser_for_dex_id(dex_identifier):
            parser_dex_labels = ", ".join(resolve_onchain_pool_price_parser_dex_ids())
            raise TradingConfigurationError(
                f"{TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE} contains dex id '{dex_identifier}' "
                f"without an on-chain pool price parser — parsers available: {parser_dex_labels}",
            )
        effective_dex_identifiers.append(dex_identifier)

    stablecoin_address_bindings: list[TradingStablecoinAddressBinding] = []
    for blockchain_network in effective_blockchain_networks:
        stablecoin_address = resolve_stablecoin_address_for_blockchain_from_settings(
            blockchain_network,
            configuration_settings,
        )
        _validate_configured_evm_stablecoin_against_price_metadata_registry(
            blockchain_network=blockchain_network,
            stablecoin_address=stablecoin_address,
        )
        stablecoin_address_bindings.append(
            TradingStablecoinAddressBinding(
                blockchain_network=blockchain_network,
                address=stablecoin_address,
            ),
        )

    apply_trading_capabilities_snapshot(
        TradingCapabilitiesSnapshot(
            allowed_blockchain_networks=tuple(effective_blockchain_networks),
            supported_solana_dex_identifiers=tuple(effective_dex_identifiers),
            stablecoin_address_bindings=stablecoin_address_bindings,
        ),
    )

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


def _validate_configured_evm_stablecoin_against_price_metadata_registry(
        blockchain_network: BlockchainNetwork,
        stablecoin_address: str,
) -> None:
    if not is_trading_evm_blockchain_network(blockchain_network):
        return

    normalized_stablecoin_address = stablecoin_address.strip().lower()
    if not normalized_stablecoin_address:
        return

    stablecoin_address_environment_variable = resolve_stablecoin_address_environment_variable_name(
        blockchain_network,
    )

    try:
        chain_price_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(blockchain_network)
    except ValueError as exception:
        raise TradingConfigurationError(
            f"{stablecoin_address_environment_variable} is configured for blockchain "
            f"'{blockchain_network.value}' but no EVM chain price metadata is registered",
        ) from exception

    if normalized_stablecoin_address not in chain_price_metadata.stablecoin_addresses:
        raise TradingConfigurationError(
            f"{stablecoin_address_environment_variable} value '{stablecoin_address}' is not registered "
            f"as a USD-convertible stablecoin in EVM chain price metadata for '{blockchain_network.value}'",
        )


def validate_live_wallet_configuration(
        configuration_settings: TradingApplicationBootConfigurationSettings,
) -> None:
    if configuration_settings.TRADING_PAPER_MODE:
        return

    wallet_mnemonic = configuration_settings.TRADING_WALLET_MNEMONIC.strip()
    if not wallet_mnemonic:
        raise TradingConfigurationError(
            f"{TRADING_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is required when TRADING_PAPER_MODE=false",
        )

    requires_lifi = False
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
                f"'{blockchain_network.value}' when TRADING_PAPER_MODE=false",
            )

        if blockchain_network == BlockchainNetwork.SOLANA:
            _validate_solana_wallet_derivation(
                wallet_mnemonic=wallet_mnemonic,
                wallet_derivation_index=configuration_settings.TRADING_WALLET_DERIVATION_INDEX,
            )
        elif is_trading_evm_blockchain_network(blockchain_network):
            requires_lifi = True
            _validate_evm_wallet_derivation(
                wallet_mnemonic=wallet_mnemonic,
                wallet_derivation_index=configuration_settings.TRADING_WALLET_DERIVATION_INDEX,
                blockchain_network=blockchain_network,
            )

    if requires_lifi:
        if not configuration_settings.LIFI_API_KEY.strip():
            raise TradingConfigurationError(
                f"{LIFI_API_KEY_ENVIRONMENT_VARIABLE} is required when live EVM trading chains are enabled",
            )
        if not configuration_settings.LIFI_INTEGRATION_ID.strip():
            raise TradingConfigurationError(
                f"{LIFI_INTEGRATION_ID_ENVIRONMENT_VARIABLE} is required when live EVM trading chains are enabled",
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
            f"{TRADING_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is invalid for Solana wallet derivation — {exception}",
        ) from exception


def _validate_evm_wallet_derivation(
        wallet_mnemonic: str,
        wallet_derivation_index: int,
        blockchain_network: BlockchainNetwork,
) -> None:
    try:
        from eth_account import Account

        Account.enable_unaudited_hdwallet_features()
        derivation_path = f"m/44'/60'/0'/0/{wallet_derivation_index}"
        Account.from_mnemonic(mnemonic=wallet_mnemonic, account_path=derivation_path)
    except Exception as exception:
        raise TradingConfigurationError(
            f"{TRADING_WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is invalid for EVM wallet derivation "
            f"on '{blockchain_network.value}' — {exception}",
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
    if blockchain_network == BlockchainNetwork.ROBINHOOD:
        return "TRADING_STABLECOIN_ADDRESS_ROBINHOOD"
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
    if blockchain_network == BlockchainNetwork.ROBINHOOD:
        return configuration_settings.TRADING_STABLECOIN_ADDRESS_ROBINHOOD.strip()
    raise TradingConfigurationError(
        f"No stablecoin address configured for blockchain '{blockchain_network.value}'",
    )


def resolve_stablecoin_address_for_blockchain(blockchain_network: BlockchainNetwork) -> str:
    return resolve_trading_capabilities_snapshot().resolve_stablecoin_address(blockchain_network)


def require_stablecoin_address_for_blockchain(blockchain_network: BlockchainNetwork) -> str:
    stablecoin_address = resolve_stablecoin_address_for_blockchain(blockchain_network)
    if stablecoin_address:
        return stablecoin_address

    stablecoin_address_environment_variable = resolve_stablecoin_address_environment_variable_name(blockchain_network)
    raise TradingConfigurationError(
        f"{stablecoin_address_environment_variable} is required for blockchain '{blockchain_network.value}' — "
        f"live wallet configuration must be validated at application startup",
    )
