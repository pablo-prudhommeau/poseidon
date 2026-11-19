from __future__ import annotations

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import Session

from aave_dca_test_helpers import (
    BTCB_ADDRESS,
    USDC_ADDRESS,
    WALLET_ADDRESS,
    build_aave_dca_database_session,
    build_aave_dca_order,
    build_aave_dca_strategy,
)
from src.core.aavedca.aave_dca_helpers import append_pipeline_operation, deserialize_pipeline_operations
from src.core.aavedca.aave_dca_pipeline_recovery_service import AaveDcaPipelineRecoveryService
from src.core.aavedca.aave_dca_pipeline_service import AaveDcaPipelineService
from src.core.aavedca.aave_dca_structures import (
    AaveDcaOrderStatus,
    AaveDcaPipelineOperation,
    AaveDcaPipelineOperationStatus,
    AaveDcaPipelineOperationStep,
    AaveDcaStrategyStatus,
)
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_structures import (
    AaveEvmTransactionBroadcast,
    AaveEvmTransactionConfirmationFailureKind,
    AaveEvmTransactionConfirmationOutcome,
)
from src.integrations.lifi.lifi_helpers import LIFI_EVM_DIAMOND_CONTRACT_ADDRESS
from src.integrations.lifi.lifi_structures import LifiEstimate, LifiRoute, LifiTransactionRequest
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

SOURCE_AMOUNT_BASE_UNITS: int = 50_000_000
BOUGHT_AMOUNT_BASE_UNITS: int = 78_125
MINIMUM_OUTPUT_BASE_UNITS: int = 77_425
PRE_SWAP_TARGET_BALANCE_BASE_UNITS: int = 1_000
WITHDRAWAL_BROADCAST: AaveEvmTransactionBroadcast = AaveEvmTransactionBroadcast(transaction_hash="0xwithdraw", nonce=7, submitted_gas_limit=350_000)
SWAP_BROADCAST: AaveEvmTransactionBroadcast = AaveEvmTransactionBroadcast(transaction_hash="0xswap", nonce=8, submitted_gas_limit=540_000)
SUPPLY_BROADCAST: AaveEvmTransactionBroadcast = AaveEvmTransactionBroadcast(transaction_hash="0xsupply", nonce=10, submitted_gas_limit=350_000)


def _confirmed(transaction_hash: str) -> AaveEvmTransactionConfirmationOutcome:
    return AaveEvmTransactionConfirmationOutcome(transaction_hash=transaction_hash, is_confirmed=True)


def _timed_out(transaction_hash: str) -> AaveEvmTransactionConfirmationOutcome:
    return AaveEvmTransactionConfirmationOutcome(
        transaction_hash=transaction_hash,
        is_confirmed=False,
        confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.CONFIRMATION_TIMEOUT,
    )


def _build_swap_route(router_address: str) -> LifiRoute:
    return LifiRoute(
        transaction_request=LifiTransactionRequest(
            to=router_address,
            data="0xabcdef",
            value="0x0",
            from_address=WALLET_ADDRESS,
            gas_limit="0x61a80",
            chain_id=43114,
        ),
        estimate=LifiEstimate(tool="1inch", to_amount=str(BOUGHT_AMOUNT_BASE_UNITS), to_amount_min=str(MINIMUM_OUTPUT_BASE_UNITS)),
    )


def _build_aave_executor(confirmation_outcomes: list[AaveEvmTransactionConfirmationOutcome]) -> MagicMock:
    aave_executor = MagicMock()
    aave_executor._initialize_provider = AsyncMock()
    aave_executor.get_wallet_address.return_value = WALLET_ADDRESS
    aave_executor.ensure_erc20_allowance = AsyncMock()
    aave_executor.reset_erc20_allowance = AsyncMock()
    aave_executor.fetch_erc20_balance = AsyncMock(return_value=PRE_SWAP_TARGET_BALANCE_BASE_UNITS)
    aave_executor.simulate_evm_transaction_before_broadcast = AsyncMock(return_value=None)
    aave_executor.broadcast_withdrawal = AsyncMock(return_value=WITHDRAWAL_BROADCAST)
    aave_executor.broadcast_raw_evm_transaction = AsyncMock(return_value=SWAP_BROADCAST)
    aave_executor.broadcast_supply = AsyncMock(return_value=SUPPLY_BROADCAST)
    aave_executor.resolve_transaction_confirmation_outcome = AsyncMock(side_effect=confirmation_outcomes)
    aave_executor.inspect_broadcast_transaction = AsyncMock(return_value=None)
    return aave_executor


def _build_preflight_service(target_asset_balance_base_units: int) -> MagicMock:
    preflight_service = MagicMock()
    preflight_service.run_live_pipeline_preflight = AsyncMock()
    preflight_service.poll_target_asset_balance_after_swap = AsyncMock(return_value=target_asset_balance_base_units)
    return preflight_service


def _build_pipeline_service(database_session: Session, aave_executor: MagicMock, preflight_service: MagicMock) -> AaveDcaPipelineService:
    order_dao = AaveDcaOrderDao(database_session)
    return AaveDcaPipelineService(
        database_session=database_session,
        dca_order_dao=order_dao,
        dca_strategy_dao=AaveDcaStrategyDao(database_session),
        aave_executor=aave_executor,
        preflight_service=preflight_service,
        recovery_service=AaveDcaPipelineRecoveryService(database_session, order_dao),
    )


def _persist_strategy(database_session: Session) -> AaveDcaStrategy:
    dca_strategy = build_aave_dca_strategy(AaveDcaStrategyStatus.ACTIVE, BlockchainNetwork.AVALANCHE.value)
    database_session.add(dca_strategy)
    database_session.commit()
    return dca_strategy


def _persist_order(database_session: Session, dca_strategy: AaveDcaStrategy, order_status: AaveDcaOrderStatus) -> AaveDcaOrder:
    dca_order = build_aave_dca_order(dca_strategy.id, order_status, None)
    database_session.add(dca_order)
    database_session.commit()
    return dca_order


def _run_live_pipeline(
        pipeline_service: AaveDcaPipelineService,
        dca_order: AaveDcaOrder,
        dca_strategy: AaveDcaStrategy,
        swap_route: LifiRoute,
) -> None:
    with (
        patch("src.core.aavedca.aave_dca_pipeline_service.settings") as mock_settings,
        patch("src.core.aavedca.aave_dca_pipeline_service.generate_token_to_token_route", return_value=swap_route),
        patch(
            "src.core.aavedca.aave_dca_pipeline_service.fetch_exponential_moving_average_and_price",
            new=AsyncMock(return_value=MagicMock(latest_closing_price=64_000.0)),
        ),
        patch("src.core.aavedca.aave_dca_pipeline_service.publish_dca_order_telegram_message"),
        patch("src.core.aavedca.aave_dca_pipeline_recovery_service.publish_dca_order_telegram_message"),
    ):
        mock_settings.AAVE_DCA_PAPER_MODE = False
        mock_settings.AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT = 0.5
        mock_settings.AAVE_DCA_SWAP_SETTLEMENT_POLL_INTERVAL_SECONDS = 0.0
        mock_settings.AAVE_DCA_SWAP_SETTLEMENT_POLL_TIMEOUT_SECONDS = 0.0
        asyncio.run(pipeline_service.execute_onchain_defi_routing_pipeline(dca_order, dca_strategy))


def _operations(dca_order: AaveDcaOrder, pipeline_step: AaveDcaPipelineOperationStep) -> list[AaveDcaPipelineOperation]:
    return [
        pipeline_operation
        for pipeline_operation in deserialize_pipeline_operations(dca_order.pipeline_operations).pipeline_operations
        if pipeline_operation.step == pipeline_step
    ]


def test_execute_live_pipeline_supplies_only_the_amount_bought() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_WITHDRAW)
    aave_executor = _build_aave_executor([_confirmed("0xwithdraw"), _confirmed("0xswap"), _confirmed("0xsupply")])
    pipeline_service = _build_pipeline_service(
        database_session,
        aave_executor,
        _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS),
    )

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    assert dca_order.order_status == AaveDcaOrderStatus.EXECUTED
    aave_executor.broadcast_supply.assert_awaited_once_with(BlockchainNetwork.AVALANCHE, BTCB_ADDRESS, BOUGHT_AMOUNT_BASE_UNITS)
    assert dca_order.executed_target_asset_amount == BOUGHT_AMOUNT_BASE_UNITS / 10 ** 8


def test_execute_live_pipeline_approves_the_exact_amount_and_resets_the_router_allowance() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_WITHDRAW)
    aave_executor = _build_aave_executor([_confirmed("0xwithdraw"), _confirmed("0xswap"), _confirmed("0xsupply")])
    pipeline_service = _build_pipeline_service(
        database_session,
        aave_executor,
        _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS),
    )

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    aave_executor.ensure_erc20_allowance.assert_awaited_once_with(
        chain=BlockchainNetwork.AVALANCHE,
        token_address=USDC_ADDRESS,
        spender_address=LIFI_EVM_DIAMOND_CONTRACT_ADDRESS,
        required_amount_wei=SOURCE_AMOUNT_BASE_UNITS,
    )
    aave_executor.reset_erc20_allowance.assert_awaited_once_with(
        chain=BlockchainNetwork.AVALANCHE,
        token_address=USDC_ADDRESS,
        spender_address=LIFI_EVM_DIAMOND_CONTRACT_ADDRESS,
    )


def test_execute_live_pipeline_records_each_broadcast_before_waiting_for_its_confirmation() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_WITHDRAW)
    statuses_seen_at_confirmation: list[AaveDcaPipelineOperationStatus] = []

    async def confirm_after_checking_the_record(
            chain: BlockchainNetwork,
            transaction_hash_hex: str,
            submitted_gas_limit: Optional[int],
    ) -> AaveEvmTransactionConfirmationOutcome:
        last_operation: AaveDcaPipelineOperation = deserialize_pipeline_operations(dca_order.pipeline_operations).pipeline_operations[-1]
        assert last_operation.transaction_hash == transaction_hash_hex
        statuses_seen_at_confirmation.append(last_operation.status)
        return _confirmed(transaction_hash_hex)

    aave_executor = _build_aave_executor([])
    aave_executor.resolve_transaction_confirmation_outcome = AsyncMock(side_effect=confirm_after_checking_the_record)
    pipeline_service = _build_pipeline_service(
        database_session,
        aave_executor,
        _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS),
    )

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    assert statuses_seen_at_confirmation == [AaveDcaPipelineOperationStatus.BROADCASTED] * 3
    completed_swap_operation: AaveDcaPipelineOperation = _operations(dca_order, AaveDcaPipelineOperationStep.SWAP)[0]
    assert completed_swap_operation.status == AaveDcaPipelineOperationStatus.COMPLETED
    assert completed_swap_operation.nonce == 8
    assert completed_swap_operation.pre_swap_target_balance_base_units == PRE_SWAP_TARGET_BALANCE_BASE_UNITS


def test_execute_live_pipeline_refuses_a_foreign_destination_before_any_swap_is_signed() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SWAP)
    aave_executor = _build_aave_executor([])
    pipeline_service = _build_pipeline_service(database_session, aave_executor, _build_preflight_service(0))

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(USDC_ADDRESS))

    aave_executor.broadcast_raw_evm_transaction.assert_not_called()
    assert dca_order.suspension_reason == "LIFI_TRANSACTION_REJECTED"
    assert _operations(dca_order, AaveDcaPipelineOperationStep.SWAP)[-1].failure_code == "LIFI_TRANSACTION_REJECTED"


def test_execute_live_pipeline_never_sends_a_swap_twice_after_a_confirmation_timeout() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SWAP)
    aave_executor = _build_aave_executor([_timed_out("0xswap"), _confirmed("0xsupply")])
    preflight_service = _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS)
    pipeline_service = _build_pipeline_service(database_session, aave_executor, preflight_service)

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    assert dca_order.order_status == AaveDcaOrderStatus.AWAITING_SWAP
    assert dca_order.pipeline_attempt_count == 1
    assert _operations(dca_order, AaveDcaPipelineOperationStep.SWAP)[-1].status == AaveDcaPipelineOperationStatus.BROADCASTED

    aave_executor.inspect_broadcast_transaction = AsyncMock(return_value=_confirmed("0xswap"))
    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    aave_executor.broadcast_raw_evm_transaction.assert_awaited_once()
    aave_executor.inspect_broadcast_transaction.assert_awaited_once_with(chain=BlockchainNetwork.AVALANCHE, transaction_hash_hex="0xswap", nonce=8)
    assert preflight_service.run_live_pipeline_preflight.await_args.kwargs["has_pending_broadcast"] is True
    assert dca_order.order_status == AaveDcaOrderStatus.EXECUTED


def test_execute_live_pipeline_sends_nothing_while_the_swap_is_still_pending() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SWAP)
    aave_executor = _build_aave_executor([_timed_out("0xswap")])
    pipeline_service = _build_pipeline_service(database_session, aave_executor, _build_preflight_service(0))

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))
    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    aave_executor.broadcast_raw_evm_transaction.assert_awaited_once()
    assert dca_order.order_status == AaveDcaOrderStatus.AWAITING_SWAP
    assert dca_order.pipeline_attempt_count == 2


def test_execute_live_pipeline_sends_a_dropped_swap_again_exactly_once() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SWAP)
    aave_executor = _build_aave_executor([_timed_out("0xswap"), _confirmed("0xswap"), _confirmed("0xsupply")])
    pipeline_service = _build_pipeline_service(
        database_session,
        aave_executor,
        _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS),
    )

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))
    aave_executor.inspect_broadcast_transaction = AsyncMock(
        return_value=AaveEvmTransactionConfirmationOutcome(
            transaction_hash="0xswap",
            is_confirmed=False,
            confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REPLACED_OR_DROPPED,
        )
    )
    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    assert aave_executor.broadcast_raw_evm_transaction.await_count == 1
    assert _operations(dca_order, AaveDcaPipelineOperationStep.SWAP)[-1].status == AaveDcaPipelineOperationStatus.FAILED

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    assert aave_executor.broadcast_raw_evm_transaction.await_count == 2
    assert dca_order.order_status == AaveDcaOrderStatus.EXECUTED


def test_execute_live_pipeline_never_withdraws_twice_after_a_late_confirmation() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_WITHDRAW)
    aave_executor = _build_aave_executor([_timed_out("0xwithdraw"), _confirmed("0xswap"), _confirmed("0xsupply")])
    pipeline_service = _build_pipeline_service(
        database_session,
        aave_executor,
        _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS),
    )

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))
    aave_executor.inspect_broadcast_transaction = AsyncMock(return_value=_confirmed("0xwithdraw"))
    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    aave_executor.broadcast_withdrawal.assert_awaited_once()
    assert dca_order.order_status == AaveDcaOrderStatus.EXECUTED


def test_execute_live_pipeline_never_supplies_twice_after_a_late_confirmation() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SWAP)
    aave_executor = _build_aave_executor([_confirmed("0xswap"), _timed_out("0xsupply")])
    pipeline_service = _build_pipeline_service(
        database_session,
        aave_executor,
        _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS),
    )

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))
    assert dca_order.order_status == AaveDcaOrderStatus.AWAITING_SUPPLY

    aave_executor.inspect_broadcast_transaction = AsyncMock(return_value=_confirmed("0xsupply"))
    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    aave_executor.broadcast_supply.assert_awaited_once()
    assert dca_order.order_status == AaveDcaOrderStatus.EXECUTED
    assert dca_order.executed_target_asset_amount == BOUGHT_AMOUNT_BASE_UNITS / 10 ** 8


def test_execute_live_pipeline_supplies_nothing_without_a_recorded_pre_swap_balance() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SUPPLY)
    dca_order.pipeline_operations = append_pipeline_operation(
        dca_order.pipeline_operations,
        AaveDcaPipelineOperation(
            step=AaveDcaPipelineOperationStep.SWAP,
            status=AaveDcaPipelineOperationStatus.COMPLETED,
            transaction_hash="0xswap",
            minimum_output_base_units=MINIMUM_OUTPUT_BASE_UNITS,
        ),
    )
    aave_executor = _build_aave_executor([])
    pipeline_service = _build_pipeline_service(database_session, aave_executor, _build_preflight_service(10 ** 8))

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    aave_executor.broadcast_supply.assert_not_called()
    assert dca_order.suspension_reason == "PRE_SWAP_BALANCE_MISSING"


def test_execute_live_pipeline_supplies_nothing_when_the_bought_amount_is_not_positive() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SUPPLY)
    dca_order.pipeline_operations = append_pipeline_operation(
        dca_order.pipeline_operations,
        AaveDcaPipelineOperation(
            step=AaveDcaPipelineOperationStep.SWAP,
            status=AaveDcaPipelineOperationStatus.COMPLETED,
            transaction_hash="0xswap",
            minimum_output_base_units=0,
            pre_swap_target_balance_base_units=PRE_SWAP_TARGET_BALANCE_BASE_UNITS,
        ),
    )
    aave_executor = _build_aave_executor([])
    pipeline_service = _build_pipeline_service(database_session, aave_executor, _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS))

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    aave_executor.broadcast_supply.assert_not_called()
    assert dca_order.suspension_reason == "EMPTY_DEPOSIT_AMOUNT"


def test_execute_live_pipeline_completes_the_order_when_the_router_allowance_reset_fails() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_SWAP)
    aave_executor = _build_aave_executor([_confirmed("0xswap"), _confirmed("0xsupply")])
    aave_executor.reset_erc20_allowance = AsyncMock(side_effect=RuntimeError("ERC20 allowance approval not confirmed"))
    pipeline_service = _build_pipeline_service(
        database_session,
        aave_executor,
        _build_preflight_service(PRE_SWAP_TARGET_BALANCE_BASE_UNITS + BOUGHT_AMOUNT_BASE_UNITS),
    )

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    assert dca_order.order_status == AaveDcaOrderStatus.EXECUTED


def test_execute_live_pipeline_suspends_the_order_when_a_transaction_cannot_be_sent() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session)
    dca_order = _persist_order(database_session, dca_strategy, AaveDcaOrderStatus.AWAITING_WITHDRAW)
    aave_executor = _build_aave_executor([])
    aave_executor.broadcast_withdrawal = AsyncMock(side_effect=RuntimeError("nonce too low"))
    pipeline_service = _build_pipeline_service(database_session, aave_executor, _build_preflight_service(0))

    _run_live_pipeline(pipeline_service, dca_order, dca_strategy, _build_swap_route(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS))

    assert dca_order.suspension_reason == "ONCHAIN_EXECUTION_FAILED"
    assert _operations(dca_order, AaveDcaPipelineOperationStep.WITHDRAW)[-1].failure_message == "nonce too low"
