from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.trading_execution_handler_service import resolve_execution_chain_handler_for_blockchain
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def build_route_for_live_sell(
        token_mint: str,
        chain: BlockchainNetwork,
        token_quantity: float,
        token_decimals: int,
) -> Optional[BlockchainExecutionRoute]:
    if settings.PAPER_MODE:
        return None

    chain_handler = resolve_execution_chain_handler_for_blockchain(chain)
    if chain_handler is None:
        logger.warning(
            "[TRADING][EXECUTION][ROUTE] Sell route denied — no handler for blockchain_network=%s",
            chain.value,
        )
        return None

    return chain_handler.build_sell_route(token_mint, token_quantity, token_decimals)


def build_route_for_live_execution(candidate: TradingCandidate, order_notional_usd: float) -> Optional[BlockchainExecutionRoute]:
    if settings.PAPER_MODE:
        return None

    chain = candidate.token.chain
    chain_handler = resolve_execution_chain_handler_for_blockchain(chain)
    if chain_handler is None:
        logger.warning(
            "[TRADING][EXECUTION][ROUTE] Buy route denied — no handler for blockchain_network=%s token=%s",
            chain.value,
            candidate.token.symbol,
        )
        return None

    return chain_handler.build_buy_route(candidate, order_notional_usd)
