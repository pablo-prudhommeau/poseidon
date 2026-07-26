from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_structures import (
    GasRefillBudgetDetailScope,
    TradingCapabilitiesSnapshot,
    TradingConfigurationError,
)

TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS: tuple[BlockchainNetwork, ...] = (
    BlockchainNetwork.SOLANA,
    BlockchainNetwork.ROBINHOOD,
    BlockchainNetwork.BASE,
    BlockchainNetwork.BSC,
)

_trading_capabilities_snapshot: TradingCapabilitiesSnapshot | None = None


def apply_trading_capabilities_snapshot(snapshot: TradingCapabilitiesSnapshot) -> None:
    global _trading_capabilities_snapshot
    _trading_capabilities_snapshot = snapshot


def resolve_trading_capabilities_snapshot() -> TradingCapabilitiesSnapshot:
    if _trading_capabilities_snapshot is None:
        raise TradingConfigurationError(
            "Trading capabilities snapshot has not been applied — application startup validation must run first",
        )
    return _trading_capabilities_snapshot


def resolve_trading_allowed_blockchain_networks() -> list[BlockchainNetwork]:
    return list(resolve_trading_capabilities_snapshot().allowed_blockchain_networks)


def resolve_trading_allowed_blockchain_network_identifiers() -> tuple[str, ...]:
    return tuple(
        blockchain_network.value
        for blockchain_network in resolve_trading_allowed_blockchain_networks()
    )


def is_trading_evm_blockchain_network(blockchain_network: BlockchainNetwork) -> bool:
    return blockchain_network in {
        BlockchainNetwork.ROBINHOOD,
        BlockchainNetwork.BASE,
        BlockchainNetwork.BSC,
    }


def resolve_gas_refill_budget_detail_scope(
        blockchain_network: BlockchainNetwork,
) -> GasRefillBudgetDetailScope | None:
    if blockchain_network == BlockchainNetwork.PAPER:
        return None
    if blockchain_network == BlockchainNetwork.SOLANA:
        return GasRefillBudgetDetailScope.SOLANA_WITH_TOKEN_ACCOUNT_RENT
    return GasRefillBudgetDetailScope.EVM_SWAP_FEES_ONLY
