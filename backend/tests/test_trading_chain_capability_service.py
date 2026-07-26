from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_chain_capability_service import (
    TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS,
    is_trading_evm_blockchain_network,
    resolve_gas_refill_budget_detail_scope,
    resolve_trading_allowed_blockchain_network_identifiers,
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_structures import GasRefillBudgetDetailScope


def test_trading_application_supported_blockchain_networks_constant_contains_quartet() -> None:
    assert TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS == (
        BlockchainNetwork.SOLANA,
        BlockchainNetwork.ROBINHOOD,
        BlockchainNetwork.BASE,
        BlockchainNetwork.BSC,
    )


def test_resolve_trading_allowed_blockchain_networks_uses_effective_settings_configuration() -> None:
    assert settings.TRADING_ALLOWED_CHAINS == ["solana", "robinhood", "base", "bsc"]
    assert resolve_trading_allowed_blockchain_networks() == [
        BlockchainNetwork.SOLANA,
        BlockchainNetwork.ROBINHOOD,
        BlockchainNetwork.BASE,
        BlockchainNetwork.BSC,
    ]


def test_resolve_trading_allowed_blockchain_network_identifiers_uses_effective_settings_configuration() -> None:
    assert resolve_trading_allowed_blockchain_network_identifiers() == ("solana", "robinhood", "base", "bsc")


def test_resolve_gas_refill_budget_detail_scope_maps_solana_and_evm_families() -> None:
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.SOLANA) == GasRefillBudgetDetailScope.SOLANA_WITH_TOKEN_ACCOUNT_RENT
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.BSC) == GasRefillBudgetDetailScope.EVM_SWAP_FEES_ONLY
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.BASE) == GasRefillBudgetDetailScope.EVM_SWAP_FEES_ONLY
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.ROBINHOOD) == GasRefillBudgetDetailScope.EVM_SWAP_FEES_ONLY
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.PAPER) is None


def test_is_trading_evm_blockchain_network_only_allows_robinhood_base_bsc() -> None:
    assert is_trading_evm_blockchain_network(BlockchainNetwork.ROBINHOOD) is True
    assert is_trading_evm_blockchain_network(BlockchainNetwork.BASE) is True
    assert is_trading_evm_blockchain_network(BlockchainNetwork.BSC) is True
    assert is_trading_evm_blockchain_network(BlockchainNetwork.AVALANCHE) is False
    assert is_trading_evm_blockchain_network(BlockchainNetwork.SOLANA) is False
    assert is_trading_evm_blockchain_network(BlockchainNetwork.PAPER) is False
