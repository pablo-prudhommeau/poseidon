from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_chain_capability_service import (
    TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS,
    resolve_gas_refill_budget_detail_scope,
    resolve_trading_allowed_blockchain_network_identifiers,
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_structures import GasRefillBudgetDetailScope


def test_trading_application_supported_blockchain_networks_constant_contains_solana_only() -> None:
    assert TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS == (BlockchainNetwork.SOLANA,)


def test_resolve_trading_allowed_blockchain_networks_uses_effective_settings_configuration() -> None:
    assert settings.TRADING_ALLOWED_CHAINS == ["solana"]
    assert resolve_trading_allowed_blockchain_networks() == [BlockchainNetwork.SOLANA]


def test_resolve_trading_allowed_blockchain_network_identifiers_uses_effective_settings_configuration() -> None:
    assert resolve_trading_allowed_blockchain_network_identifiers() == ("solana",)


def test_resolve_gas_refill_budget_detail_scope_maps_solana_and_evm_families() -> None:
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.SOLANA) == GasRefillBudgetDetailScope.SOLANA_WITH_TOKEN_ACCOUNT_RENT
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.BSC) == GasRefillBudgetDetailScope.EVM_SWAP_FEES_ONLY
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.BASE) == GasRefillBudgetDetailScope.EVM_SWAP_FEES_ONLY
    assert resolve_gas_refill_budget_detail_scope(BlockchainNetwork.PAPER) is None
