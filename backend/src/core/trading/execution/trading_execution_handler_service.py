from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.evm.trading_execution_evm_handler import TradingExecutionEvmHandler
from src.core.trading.execution.solana.trading_execution_solana_handler import TradingExecutionSolanaHandler
from src.core.trading.execution.trading_execution_chain_handler import TradingExecutionChainHandler
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_BLOCKCHAIN_NETWORKS = {
    BlockchainNetwork.BSC,
    BlockchainNetwork.BASE,
    BlockchainNetwork.AVALANCHE,
}


def resolve_execution_chain_handlers() -> list[TradingExecutionChainHandler]:
    if settings.PAPER_MODE:
        return []

    handlers: list[TradingExecutionChainHandler] = []
    for chain_name in settings.TRADING_ALLOWED_CHAINS:
        normalized_chain_name = chain_name.strip().lower()
        try:
            blockchain_network = BlockchainNetwork(normalized_chain_name)
        except ValueError:
            logger.warning(
                "[TRADING][EXECUTION][HANDLER][SERVICE] Unknown allowed chain ignored — "
                "configured_chain_name=%s reason=unknown_allowed_chain",
                normalized_chain_name,
            )
            continue

        if blockchain_network == BlockchainNetwork.SOLANA:
            handlers.append(TradingExecutionSolanaHandler())
            continue

        if blockchain_network in EVM_BLOCKCHAIN_NETWORKS:
            handlers.append(TradingExecutionEvmHandler(blockchain_network=blockchain_network))

    return handlers


def resolve_execution_chain_handler_for_blockchain(
        blockchain_network: BlockchainNetwork,
) -> TradingExecutionChainHandler | None:
    for handler in resolve_execution_chain_handlers():
        if handler.blockchain_network() == blockchain_network:
            return handler
    return None
