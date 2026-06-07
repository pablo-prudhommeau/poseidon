from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from src.core.structures.structures import BlockchainNetwork

from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_structures import TradingGasReserveSolanaCostSnapshot
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_gas_budget_service import (
    build_solana_gas_budget_snapshot,
)
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service import (
    _resolve_reclaimable_token_accounts,
)
from src.core.trading.walletmaintenance.trading_wallet_maintenance_service import (
    resolve_wallet_maintenance_chain_handlers,
)
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_SPL_TOKEN_PROGRAM_ID,
    SOLANA_TOKEN_2022_PROGRAM_ID,
    SolanaWalletTokenAccountSnapshot,
)


def test_build_solana_gas_budget_snapshot_with_cycle_numbers() -> None:
    cost_snapshot = TradingGasReserveSolanaCostSnapshot(
        max_open_positions=10,
        token_account_rent_lamports=2_039_280,
        average_swap_fee_lamports=500_000,
        per_position_cost_lamports=2_039_280 + (3 * 500_000),
        cycle_cost_lamports=10 * (2_039_280 + (3 * 500_000)),
    )
    with patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_gas_budget_service.settings"
    ) as mock_settings:
        mock_settings.TRADING_GAS_MINIMUM_CYCLE_NUMBER = 4
        mock_settings.TRADING_GAS_REFILL_TARGET_CYCLE_NUMBER = 40
        with patch(
            "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_gas_budget_service.build_solana_gas_reserve_cost_snapshot",
            return_value=cost_snapshot,
        ):
            snapshot = build_solana_gas_budget_snapshot()

    assert snapshot.max_open_positions == 10
    assert snapshot.cycle_cost_lamports == 10 * (2_039_280 + 3 * 500_000)
    assert snapshot.refill_threshold_lamports == snapshot.cycle_cost_lamports * 4
    assert snapshot.refill_target_lamports == snapshot.cycle_cost_lamports * 40


def test_resolve_wallet_maintenance_chain_handlers_disabled() -> None:
    with patch(
        "src.core.trading.walletmaintenance.trading_wallet_maintenance_service.settings"
    ) as mock_settings:
        mock_settings.PAPER_MODE = True
        mock_settings.TRADING_WALLET_MAINTENANCE_ENABLED = True

        handlers = resolve_wallet_maintenance_chain_handlers()

    assert handlers == []


def test_resolve_wallet_maintenance_chain_handlers_solana_only() -> None:
    with patch(
        "src.core.trading.walletmaintenance.trading_wallet_maintenance_service.settings"
    ) as mock_settings, patch(
        "src.core.trading.walletmaintenance.trading_wallet_maintenance_service.resolve_trading_allowed_blockchain_networks",
        return_value=[BlockchainNetwork.SOLANA],
    ):
        mock_settings.PAPER_MODE = False
        mock_settings.TRADING_WALLET_MAINTENANCE_ENABLED = True

        handlers = resolve_wallet_maintenance_chain_handlers()

    handler_networks = [handler.blockchain_network().value for handler in handlers]
    assert handler_networks == ["solana"]


def test_resolve_reclaimable_token_accounts_accepts_token_2022_accounts_with_old_on_chain_activity() -> None:
    token_account = SolanaWalletTokenAccountSnapshot(
        token_account_address="CcsuJdbtXdXUnxJbF3Ceyq8rG7nuKHj1G7WMbZLrGQHY",
        token_mint_address="Hkpi2SkNWm5LogyY1Bz4zYTq5REVvco2aYWd1tYppump",
        balance_raw=0,
        owner_program_id=SOLANA_TOKEN_2022_PROGRAM_ID,
        account_state="initialized",
    )
    now = datetime(2026, 5, 30, 12, 0, 0).astimezone()
    old_activity = now - timedelta(hours=100)

    with patch(
        "src.core.trading.trading_configuration_service.resolve_stablecoin_address_for_blockchain",
        return_value="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.settings"
    ) as mock_settings, patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.get_current_local_datetime",
        return_value=now,
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.resolve_cached_token_account_last_activity_datetime",
        return_value=old_activity,
    ):
        mock_settings.TRADING_SOLANA_TOKEN_ACCOUNT_RECLAIM_INACTIVE_HOURS = 72.0
        reclaimable = _resolve_reclaimable_token_accounts(
            rpc_url="https://example.invalid",
            token_accounts=[token_account],
        )

    assert len(reclaimable) == 1
    assert reclaimable[0].token_account_address == token_account.token_account_address
    assert reclaimable[0].owner_program_id == SOLANA_TOKEN_2022_PROGRAM_ID


def test_resolve_reclaimable_token_accounts_skips_when_mint_has_non_zero_balance() -> None:
    empty_token_account = SolanaWalletTokenAccountSnapshot(
        token_account_address="EmptyAccount1111111111111111111111111111111",
        token_mint_address="Hkpi2SkNWm5LogyY1Bz4zYTq5REVvco2aYWd1tYppump",
        balance_raw=0,
        owner_program_id=SOLANA_SPL_TOKEN_PROGRAM_ID,
        account_state="initialized",
    )
    active_token_account = SolanaWalletTokenAccountSnapshot(
        token_account_address="ActiveAccount111111111111111111111111111111",
        token_mint_address="Hkpi2SkNWm5LogyY1Bz4zYTq5REVvco2aYWd1tYppump",
        balance_raw=1_000_000,
        owner_program_id=SOLANA_SPL_TOKEN_PROGRAM_ID,
        account_state="initialized",
    )
    now = datetime(2026, 5, 30, 12, 0, 0).astimezone()

    with patch(
        "src.core.trading.trading_configuration_service.resolve_stablecoin_address_for_blockchain",
        return_value="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.settings"
    ) as mock_settings, patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.get_current_local_datetime",
        return_value=now,
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.resolve_cached_token_account_last_activity_datetime",
    ) as mock_fetch_last_activity:
        mock_settings.TRADING_SOLANA_TOKEN_ACCOUNT_RECLAIM_INACTIVE_HOURS = 72.0
        reclaimable = _resolve_reclaimable_token_accounts(
            rpc_url="https://example.invalid",
            token_accounts=[empty_token_account, active_token_account],
        )

    mock_fetch_last_activity.assert_not_called()
    assert reclaimable == []


def test_resolve_reclaimable_token_accounts_skips_recent_on_chain_activity() -> None:
    token_account = SolanaWalletTokenAccountSnapshot(
        token_account_address="RecentAccount111111111111111111111111111111",
        token_mint_address="Hkpi2SkNWm5LogyY1Bz4zYTq5REVvco2aYWd1tYppump",
        balance_raw=0,
        owner_program_id=SOLANA_SPL_TOKEN_PROGRAM_ID,
        account_state="initialized",
    )
    now = datetime(2026, 5, 30, 12, 0, 0).astimezone()
    recent_activity = now - timedelta(hours=24)

    with patch(
        "src.core.trading.trading_configuration_service.resolve_stablecoin_address_for_blockchain",
        return_value="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.settings"
    ) as mock_settings, patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.get_current_local_datetime",
        return_value=now,
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.resolve_cached_token_account_last_activity_datetime",
        return_value=recent_activity,
    ):
        mock_settings.TRADING_SOLANA_TOKEN_ACCOUNT_RECLAIM_INACTIVE_HOURS = 72.0
        reclaimable = _resolve_reclaimable_token_accounts(
            rpc_url="https://example.invalid",
            token_accounts=[token_account],
        )

    assert reclaimable == []


def test_resolve_reclaimable_token_accounts_skips_without_on_chain_transaction_history() -> None:
    token_account = SolanaWalletTokenAccountSnapshot(
        token_account_address="NoHistoryAccount111111111111111111111111111",
        token_mint_address="Hkpi2SkNWm5LogyY1Bz4zYTq5REVvco2aYWd1tYppump",
        balance_raw=0,
        owner_program_id=SOLANA_SPL_TOKEN_PROGRAM_ID,
        account_state="initialized",
    )
    now = datetime(2026, 5, 30, 12, 0, 0).astimezone()

    with patch(
        "src.core.trading.trading_configuration_service.resolve_stablecoin_address_for_blockchain",
        return_value="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.settings"
    ) as mock_settings, patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.get_current_local_datetime",
        return_value=now,
    ), patch(
        "src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service.resolve_cached_token_account_last_activity_datetime",
        return_value=None,
    ):
        mock_settings.TRADING_SOLANA_TOKEN_ACCOUNT_RECLAIM_INACTIVE_HOURS = 72.0
        reclaimable = _resolve_reclaimable_token_accounts(
            rpc_url="https://example.invalid",
            token_accounts=[token_account],
        )

    assert reclaimable == []
