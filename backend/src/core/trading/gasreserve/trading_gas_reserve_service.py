from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.evm.trading_gas_reserve_evm_handler import TradingGasReserveEvmHandler
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_handler import TradingGasReserveSolanaHandler
from src.core.trading.gasreserve.trading_gas_reserve_chain_handler import TradingGasReserveChainHandler
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_BLOCKCHAIN_NETWORKS = {
    BlockchainNetwork.BSC,
    BlockchainNetwork.BASE,
    BlockchainNetwork.AVALANCHE,
}


def resolve_gas_reserve_chain_handlers() -> list[TradingGasReserveChainHandler]:
    if settings.PAPER_MODE:
        return []

    handlers: list[TradingGasReserveChainHandler] = []
    for chain_name in settings.TRADING_ALLOWED_CHAINS:
        normalized_chain_name = chain_name.strip().lower()
        try:
            blockchain_network = BlockchainNetwork(normalized_chain_name)
        except ValueError:
            logger.warning(
                "[TRADING][GASRESERVE][SERVICE] Unknown allowed chain ignored — "
                "configured_chain_name=%s reason=unknown_allowed_chain",
                normalized_chain_name,
            )
            continue

        if blockchain_network == BlockchainNetwork.SOLANA:
            handlers.append(TradingGasReserveSolanaHandler())
            continue

        if blockchain_network in EVM_BLOCKCHAIN_NETWORKS:
            handlers.append(TradingGasReserveEvmHandler(blockchain_network=blockchain_network))

    return handlers


def resolve_gas_reserve_chain_handler_for_blockchain(
        blockchain_network: BlockchainNetwork,
) -> TradingGasReserveChainHandler | None:
    for handler in resolve_gas_reserve_chain_handlers():
        if handler.blockchain_network() == blockchain_network:
            return handler
    return None


def is_gas_reserve_sufficient_for_buy(blockchain_network: BlockchainNetwork) -> bool:
    if settings.PAPER_MODE:
        return True

    chain_handler = resolve_gas_reserve_chain_handler_for_blockchain(blockchain_network)
    if chain_handler is None:
        logger.warning(
            "[TRADING][GASRESERVE][SERVICE][GUARD] Buy blocked — no gas reserve handler for blockchain — "
            "blockchain_network=%s reason=gas_reserve_handler_unavailable",
            blockchain_network.value,
        )
        return False

    return chain_handler.is_gas_reserve_sufficient_for_buy()
