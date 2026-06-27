from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.solana.trading_execution_solana_handler import TradingExecutionSolanaHandler
from src.core.trading.execution.trading_execution_chain_handler import TradingExecutionChainHandler
from src.core.trading.trading_chain_capability_service import (
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_structures import TradingConfigurationError


def resolve_execution_chain_handlers() -> list[TradingExecutionChainHandler]:
    if settings.TRADING_PAPER_MODE:
        return []

    handlers: list[TradingExecutionChainHandler] = []
    for blockchain_network in resolve_trading_allowed_blockchain_networks():
        if blockchain_network == BlockchainNetwork.SOLANA:
            handlers.append(TradingExecutionSolanaHandler())
    return handlers


def resolve_execution_chain_handler_for_blockchain(
        blockchain_network: BlockchainNetwork,
) -> TradingExecutionChainHandler:
    for handler in resolve_execution_chain_handlers():
        if handler.blockchain_network() == blockchain_network:
            return handler
    raise TradingConfigurationError(
        f"No execution chain handler registered for configured blockchain '{blockchain_network.value}'",
    )
