from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.trading_execution_position_service import execute_closing_sell
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.solana.solana_structures import SolanaRpcFailureReason
from src.persistence.models import PositionPhase, TradingPosition


def _build_position(phase: PositionPhase) -> TradingPosition:
    return TradingPosition(
        id=7,
        evaluation_id=10,
        token_symbol="REY",
        blockchain_network="solana",
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
        open_quantity=100.0,
        current_quantity=100.0,
        entry_price=1.0,
        take_profit_tier_1_price=1.2,
        take_profit_tier_2_price=1.5,
        stop_loss_price=0.8,
        position_phase=phase,
        exit_reason=None,
        opened_at=MagicMock(),
        updated_at=MagicMock(),
    )


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.resolve_execution_chain_handler_for_blockchain")
def test_execute_closing_sell_reverts_when_wallet_balance_rpc_unavailable(
        resolve_execution_chain_handler_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.PAPER_MODE = False
    position = _build_position(PositionPhase.CLOSING)
    position.current_quantity = 689.303435
    chain_handler = MagicMock()
    chain_handler.resolve_sell_token_decimals.return_value = 6
    chain_handler.cap_sell_quantity_to_wallet_balance.side_effect = BlockchainRpcUnavailableError(
        "rpc down",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="getTokenAccountsByOwner",
        failure_reason=SolanaRpcFailureReason.RATE_LIMITED,
    )
    resolve_execution_chain_handler_mock.return_value = chain_handler
    database_session = MagicMock()

    trade = execute_closing_sell(
        database_session=database_session,
        position=position,
        execution_price=0.000088141787,
        sell_quantity=689.303435,
        reason=PositionExitTriggerReason.STOP_LOSS,
        previous_phase=PositionPhase.PARTIAL,
    )

    assert trade.trading_trade is None
    assert position.position_phase == PositionPhase.PARTIAL
    assert position.exit_reason is None


@patch("src.integrations.blockchain.solana.solana_rpc_client.execute_solana_rpc_with_endpoint_fallbacks")
def test_list_wallet_spl_token_accounts_raises_when_all_programs_fail(
        execute_rpc_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.solana.solana_rpc_client import list_wallet_spl_token_accounts

    execute_rpc_mock.side_effect = BlockchainRpcUnavailableError(
        "rate limited",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="getTokenAccountsByOwner",
        failure_reason=SolanaRpcFailureReason.RATE_LIMITED,
    )

    with pytest.raises(BlockchainRpcUnavailableError):
        list_wallet_spl_token_accounts("https://api.mainnet-beta.solana.com", "wallet-address")


@patch("src.integrations.blockchain.solana.solana_rpc_client.execute_solana_rpc_with_endpoint_fallbacks")
def test_rpc_send_transaction_returns_signature(execute_rpc_mock: MagicMock) -> None:
    from src.integrations.blockchain.solana.solana_rpc_client import rpc_send_transaction

    execute_rpc_mock.return_value = {"result": "confirmed-signature"}

    signature = rpc_send_transaction("https://api.mainnet-beta.solana.com", b"signed-tx-bytes")

    assert signature == "confirmed-signature"
    payload = execute_rpc_mock.call_args[0][1]
    assert payload["method"] == "sendTransaction"


@patch("src.integrations.blockchain.solana.solana_rpc_client.execute_solana_rpc_with_endpoint_fallbacks")
def test_rpc_send_transaction_propagates_rate_limit(execute_rpc_mock: MagicMock) -> None:
    from src.integrations.blockchain.solana.solana_rpc_client import rpc_send_transaction

    execute_rpc_mock.side_effect = BlockchainRpcUnavailableError(
        "rate limited",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="sendTransaction",
        failure_reason=SolanaRpcFailureReason.RATE_LIMITED,
    )

    with pytest.raises(BlockchainRpcUnavailableError):
        rpc_send_transaction("https://api.mainnet-beta.solana.com", b"signed-tx-bytes")
