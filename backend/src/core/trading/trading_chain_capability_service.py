from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_structures import (
    GasRefillBudgetDetailScope,
    TradingConfigurationError,
)

TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS: tuple[BlockchainNetwork, ...] = (
    BlockchainNetwork.SOLANA,
)

_effective_trading_allowed_blockchain_networks: tuple[BlockchainNetwork, ...] | None = None


def apply_trading_allowed_blockchain_network_configuration(
        blockchain_networks: list[BlockchainNetwork],
) -> None:
    global _effective_trading_allowed_blockchain_networks
    _effective_trading_allowed_blockchain_networks = tuple(blockchain_networks)


def resolve_trading_allowed_blockchain_networks() -> list[BlockchainNetwork]:
    if _effective_trading_allowed_blockchain_networks is None:
        raise TradingConfigurationError(
            "Trading blockchain configuration has not been applied — application startup validation must run first",
        )
    return list(_effective_trading_allowed_blockchain_networks)


def resolve_trading_allowed_blockchain_network_identifiers() -> tuple[str, ...]:
    return tuple(
        blockchain_network.value
        for blockchain_network in resolve_trading_allowed_blockchain_networks()
    )


def resolve_gas_refill_budget_detail_scope(
        blockchain_network: BlockchainNetwork,
) -> GasRefillBudgetDetailScope | None:
    if blockchain_network == BlockchainNetwork.PAPER:
        return None
    if blockchain_network == BlockchainNetwork.SOLANA:
        return GasRefillBudgetDetailScope.SOLANA_WITH_TOKEN_ACCOUNT_RENT
    return GasRefillBudgetDetailScope.EVM_SWAP_FEES_ONLY
