from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.trading_execution_swap_service import run_live_sell_blocking
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute, BlockchainSolanaRoute


@patch("src.core.trading.execution.trading_execution_swap_service.resolve_execution_chain_handler_for_blockchain")
def test_run_live_sell_blocking_forwards_dex_id_to_chain_handler(
        resolve_handler_mock: MagicMock,
) -> None:
    chain_handler = MagicMock()
    resolve_handler_mock.return_value = chain_handler
    chain_handler.run_live_sell_blocking.return_value = MagicMock()

    execution_route = BlockchainExecutionRoute(
        solana_route=BlockchainSolanaRoute(serialized_transaction_base64="dGVzdA=="),
    )

    run_live_sell_blocking(
        token_symbol="SPCX",
        token_address="token-mint",
        pair_address="pair-address",
        chain=BlockchainNetwork.SOLANA,
        dex_id="pumpfun",
        quantity=1.0,
        execution_price=0.01,
        execution_route=execution_route,
        origin_evaluation_id=42,
    )

    chain_handler.run_live_sell_blocking.assert_called_once_with(
        token_symbol="SPCX",
        token_address="token-mint",
        pair_address="pair-address",
        dex_id="pumpfun",
        quantity=1.0,
        execution_price=0.01,
        execution_route=execution_route,
        origin_evaluation_id=42,
    )
