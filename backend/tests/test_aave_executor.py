from __future__ import annotations

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from web3.exceptions import TransactionNotFound

from aave_dca_test_helpers import POOL_ADDRESS, USDC_ADDRESS, WALLET_ADDRESS
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.aave.aave_structures import (
    AaveEvmTransactionBroadcast,
    AaveEvmTransactionConfirmationFailureKind,
    AaveEvmTransactionConfirmationOutcome,
)
from src.integrations.lifi.lifi_helpers import LIFI_EVM_DIAMOND_CONTRACT_ADDRESS

SENT_TRANSACTION_HASH: bytes = bytes.fromhex("ab" * 32)
SENT_TRANSACTION_HASH_HEX: str = "0x" + "ab" * 32


def _build_web3_client(current_allowance: int, transaction_count: int) -> MagicMock:
    web3_client = MagicMock()
    token_contract = web3_client.eth.contract.return_value
    token_contract.functions.allowance.return_value.call = AsyncMock(return_value=current_allowance)
    token_contract.functions.approve.return_value.build_transaction = AsyncMock(return_value={"nonce": transaction_count})
    web3_client.eth.get_transaction_count = AsyncMock(return_value=transaction_count)
    web3_client.eth.account.sign_transaction.return_value = MagicMock(raw_transaction=b"signed")
    web3_client.eth.send_raw_transaction = AsyncMock(return_value=SENT_TRANSACTION_HASH)
    return web3_client


def _build_executor(web3_client: MagicMock, is_confirmed: bool) -> AaveExecutor:
    aave_executor: AaveExecutor = object.__new__(AaveExecutor)
    aave_executor.is_initialized = True
    aave_executor.wallet_address = WALLET_ADDRESS
    aave_executor.private_key = "0x01"
    aave_pool = MagicMock()
    aave_pool.address = POOL_ADDRESS
    aave_pool.functions.withdraw.return_value.build_transaction = AsyncMock(return_value={"nonce": 7})
    aave_pool.functions.supply.return_value.build_transaction = AsyncMock(return_value={"nonce": 8})
    aave_executor.web3_clients = {BlockchainNetwork.AVALANCHE: web3_client}
    aave_executor.pool_contracts = {BlockchainNetwork.AVALANCHE: aave_pool}
    aave_executor._build_eip1559_transaction_parameters = AsyncMock(return_value={"nonce": 7})
    aave_executor.resolve_transaction_confirmation_outcome = AsyncMock(
        return_value=AaveEvmTransactionConfirmationOutcome(transaction_hash=SENT_TRANSACTION_HASH_HEX, is_confirmed=is_confirmed),
    )
    return aave_executor


async def _resolve_value(value: int) -> int:
    return value


def test_ensure_erc20_allowance_approves_exactly_the_required_amount() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    asyncio.run(aave_executor.ensure_erc20_allowance(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, 50_000_000))

    web3_client.eth.contract.return_value.functions.approve.assert_called_once_with(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, 50_000_000)


def test_ensure_erc20_allowance_sends_nothing_when_the_allowance_already_matches() -> None:
    web3_client = _build_web3_client(current_allowance=50_000_000, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    asyncio.run(aave_executor.ensure_erc20_allowance(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, 50_000_000))

    web3_client.eth.send_raw_transaction.assert_not_called()


def test_ensure_erc20_allowance_lowers_an_unlimited_allowance_to_the_required_amount() -> None:
    web3_client = _build_web3_client(current_allowance=2 ** 256 - 1, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    asyncio.run(aave_executor.ensure_erc20_allowance(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, 50_000_000))

    web3_client.eth.contract.return_value.functions.approve.assert_called_once_with(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, 50_000_000)


def test_ensure_erc20_allowance_raises_when_the_approval_is_not_confirmed() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=False)

    with pytest.raises(RuntimeError, match="not confirmed"):
        asyncio.run(aave_executor.ensure_erc20_allowance(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, 50_000_000))


def test_reset_erc20_allowance_approves_zero() -> None:
    web3_client = _build_web3_client(current_allowance=50_000_000, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    asyncio.run(aave_executor.reset_erc20_allowance(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    web3_client.eth.contract.return_value.functions.approve.assert_called_once_with(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, 0)


def test_reset_erc20_allowance_sends_nothing_when_the_allowance_is_already_zero() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    asyncio.run(aave_executor.reset_erc20_allowance(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    web3_client.eth.send_raw_transaction.assert_not_called()


def test_reset_erc20_allowance_raises_when_the_reset_is_not_confirmed() -> None:
    web3_client = _build_web3_client(current_allowance=50_000_000, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=False)

    with pytest.raises(RuntimeError, match="not confirmed"):
        asyncio.run(aave_executor.reset_erc20_allowance(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))


def test_broadcast_withdrawal_returns_hash_and_nonce_without_waiting_for_confirmation() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    withdrawal_broadcast: AaveEvmTransactionBroadcast = asyncio.run(
        aave_executor.broadcast_withdrawal(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, 50_000_000)
    )

    assert withdrawal_broadcast == AaveEvmTransactionBroadcast(transaction_hash=SENT_TRANSACTION_HASH_HEX, nonce=7, submitted_gas_limit=350_000)
    aave_executor.resolve_transaction_confirmation_outcome.assert_not_called()


def test_broadcast_raw_evm_transaction_returns_the_buffered_gas_limit() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=7)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    swap_broadcast: AaveEvmTransactionBroadcast = asyncio.run(
        aave_executor.broadcast_raw_evm_transaction(
            chain=BlockchainNetwork.AVALANCHE,
            to_address=LIFI_EVM_DIAMOND_CONTRACT_ADDRESS,
            transaction_calldata="0xabcdef",
            transaction_value_wei=0,
            gas_limit=400_000,
        )
    )

    assert swap_broadcast == AaveEvmTransactionBroadcast(transaction_hash=SENT_TRANSACTION_HASH_HEX, nonce=7, submitted_gas_limit=540_000)
    aave_executor.resolve_transaction_confirmation_outcome.assert_not_called()


def test_broadcast_supply_approves_the_pool_for_the_exact_amount_then_returns_the_supply_broadcast() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=8)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    supply_broadcast: AaveEvmTransactionBroadcast = asyncio.run(
        aave_executor.broadcast_supply(BlockchainNetwork.AVALANCHE, USDC_ADDRESS, 78_125)
    )

    web3_client.eth.contract.return_value.functions.approve.assert_called_once_with(POOL_ADDRESS, 78_125)
    assert supply_broadcast.nonce == 8
    assert web3_client.eth.send_raw_transaction.await_count == 2


def test_inspect_broadcast_transaction_reads_no_receipt_while_the_nonce_is_not_consumed() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=7)
    web3_client.eth.get_transaction_receipt = AsyncMock()
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    inspected_outcome: Optional[AaveEvmTransactionConfirmationOutcome] = asyncio.run(
        aave_executor.inspect_broadcast_transaction(BlockchainNetwork.AVALANCHE, SENT_TRANSACTION_HASH_HEX, 7)
    )

    assert inspected_outcome is None
    web3_client.eth.get_transaction_receipt.assert_not_called()


def test_inspect_broadcast_transaction_returns_the_confirmed_receipt() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=8)
    web3_client.eth.get_transaction_receipt = AsyncMock(return_value={"status": 1, "blockNumber": 100})
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    inspected_outcome: Optional[AaveEvmTransactionConfirmationOutcome] = asyncio.run(
        aave_executor.inspect_broadcast_transaction(BlockchainNetwork.AVALANCHE, SENT_TRANSACTION_HASH_HEX, 7)
    )

    assert inspected_outcome == AaveEvmTransactionConfirmationOutcome(
        transaction_hash=SENT_TRANSACTION_HASH_HEX,
        is_confirmed=True,
        block_number=100,
    )


def test_inspect_broadcast_transaction_returns_a_reverted_receipt() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=8)
    web3_client.eth.get_transaction_receipt = AsyncMock(return_value={"status": 0, "blockNumber": 100, "gasUsed": 21_000})
    aave_executor = _build_executor(web3_client, is_confirmed=True)
    aave_executor._decode_reverted_transaction_reason = AsyncMock(return_value="QUOTE_SWAP_AMOUNT_TOO_SMALL")

    inspected_outcome: Optional[AaveEvmTransactionConfirmationOutcome] = asyncio.run(
        aave_executor.inspect_broadcast_transaction(BlockchainNetwork.AVALANCHE, SENT_TRANSACTION_HASH_HEX, 7)
    )

    assert inspected_outcome is not None
    assert inspected_outcome.confirmation_failure_kind == AaveEvmTransactionConfirmationFailureKind.REVERTED
    assert inspected_outcome.onchain_revert_reason == "QUOTE_SWAP_AMOUNT_TOO_SMALL"


def test_inspect_broadcast_transaction_reads_the_receipt_again_before_declaring_a_drop() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=8)
    web3_client.eth.get_transaction_receipt = AsyncMock(
        side_effect=[TransactionNotFound("not found"), {"status": 1, "blockNumber": 100}],
    )
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    with patch("src.integrations.aave.aave_executor.asyncio.sleep", new=AsyncMock()):
        inspected_outcome: Optional[AaveEvmTransactionConfirmationOutcome] = asyncio.run(
            aave_executor.inspect_broadcast_transaction(BlockchainNetwork.AVALANCHE, SENT_TRANSACTION_HASH_HEX, 7)
        )

    assert inspected_outcome is not None
    assert inspected_outcome.is_confirmed


def test_inspect_broadcast_transaction_reports_a_dropped_transaction() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=8)
    web3_client.eth.get_transaction_receipt = AsyncMock(side_effect=TransactionNotFound("not found"))
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    with patch("src.integrations.aave.aave_executor.asyncio.sleep", new=AsyncMock()):
        inspected_outcome: Optional[AaveEvmTransactionConfirmationOutcome] = asyncio.run(
            aave_executor.inspect_broadcast_transaction(BlockchainNetwork.AVALANCHE, SENT_TRANSACTION_HASH_HEX, 7)
        )

    assert inspected_outcome == AaveEvmTransactionConfirmationOutcome(
        transaction_hash=SENT_TRANSACTION_HASH_HEX,
        is_confirmed=False,
        confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REPLACED_OR_DROPPED,
    )
    assert web3_client.eth.get_transaction_receipt.await_count == 2


def test_fetch_max_fee_per_gas_wei_is_twice_the_base_fee_plus_the_priority_fee() -> None:
    web3_client = _build_web3_client(current_allowance=0, transaction_count=7)
    web3_client.eth.get_block = AsyncMock(return_value={"baseFeePerGas": 7_500_000_000})
    web3_client.eth.max_priority_fee = _resolve_value(1_000_000)
    aave_executor = _build_executor(web3_client, is_confirmed=True)

    max_fee_per_gas_wei: int = asyncio.run(aave_executor.fetch_max_fee_per_gas_wei(BlockchainNetwork.AVALANCHE))

    assert max_fee_per_gas_wei == 15_001_000_000
