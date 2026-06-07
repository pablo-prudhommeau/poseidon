from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.trading_execution_handler_service import resolve_execution_chain_handler_for_blockchain
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute


def build_route_for_live_sell(
        token_mint: str,
        chain: BlockchainNetwork,
        token_quantity: float,
        token_decimals: int,
) -> BlockchainExecutionRoute:
    chain_handler = resolve_execution_chain_handler_for_blockchain(chain)
    return chain_handler.build_sell_route(token_mint, token_quantity, token_decimals)


def build_route_for_live_execution(candidate: TradingCandidate, order_notional_usd: float) -> BlockchainExecutionRoute:
    chain = candidate.token.chain
    chain_handler = resolve_execution_chain_handler_for_blockchain(chain)
    return chain_handler.build_buy_route(candidate, order_notional_usd)
