from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_handler import TradingGasReserveSolanaHandler
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service import (
    build_solana_gas_refill_locked_breakdown,
    compute_gas_refill_locked_stablecoin_usd_from_wallet_context,
    compute_solana_gas_refill_locked_stablecoin_snapshot,
    compute_solana_wallet_auxiliary_assets_snapshot,
)
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_structures import (
    TradingGasReserveSolanaCostSnapshot,
)
from src.core.trading.gasreserve.trading_gas_reserve_service import (
    compute_net_deployable_cash_usd,
    compute_total_gas_refill_locked_stablecoin_usd,
)
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_structures import (
    TradingWalletMaintenanceSolanaGasBudgetSnapshot,
)
from src.integrations.blockchain.solana.solana_structures import (
    SolanaOnchainWalletContext,
    SolanaWalletSnapshot,
)
from src.integrations.blockchain.solana.solana_structures import SolanaTokenAccountRentBreakdown


def _build_wallet_context(native_lamports: int, native_token_balance_usd: float) -> SolanaOnchainWalletContext:
    wallet_snapshot = SolanaWalletSnapshot(
        wallet_address="Wallet1111111111111111111111111111111111",
        rpc_url="https://example.invalid",
        token_accounts=[],
        native_lamports=native_lamports,
        fetched_at_monotonic=0.0,
    )
    rent_breakdown = SolanaTokenAccountRentBreakdown(
        active_usd=1.0,
        closable_usd=0.5,
        pending_reclaim_usd=0.0,
        locked_sol=0.01,
        active_account_count=1,
        closable_account_count=1,
        pending_reclaim_account_count=0,
    )
    native_token_balance_raw = float(native_lamports) / 1_000_000_000.0
    return SolanaOnchainWalletContext(
        wallet_snapshot=wallet_snapshot,
        rent_breakdown=rent_breakdown,
        stablecoin_balance_raw=13.76,
        native_token_balance_raw=native_token_balance_raw,
        native_token_balance_usd=native_token_balance_usd,
    )


def _build_budget_and_cost_snapshots() -> tuple[
    TradingWalletMaintenanceSolanaGasBudgetSnapshot,
    TradingGasReserveSolanaCostSnapshot,
]:
    budget_snapshot = TradingWalletMaintenanceSolanaGasBudgetSnapshot(
        max_open_positions=10,
        token_account_rent_lamports=2_039_280,
        average_swap_fee_lamports=500_000,
        cycle_cost_lamports=35_392_800,
        refill_threshold_lamports=141_571_200,
        refill_target_lamports=566_284_800,
    )
    cost_snapshot = TradingGasReserveSolanaCostSnapshot(
        max_open_positions=10,
        token_account_rent_lamports=2_039_280,
        average_swap_fee_lamports=500_000,
        per_position_cost_lamports=3_539_280,
        cycle_cost_lamports=35_392_800,
    )
    return budget_snapshot, cost_snapshot


def _expected_locked_usd_from_budget(
        budget_snapshot: TradingWalletMaintenanceSolanaGasBudgetSnapshot,
        native_token_balance_usd: float,
        native_lamports: int,
) -> float:
    native_token_balance_raw = float(native_lamports) / 1_000_000_000.0
    if native_token_balance_raw <= 0.0:
        return 0.0
    native_token_usd_price = native_token_balance_usd / native_token_balance_raw
    expected_locked_usd = (
        float(budget_snapshot.refill_target_lamports) / 1_000_000_000.0
    ) * native_token_usd_price
    return round(expected_locked_usd, 2)


def test_compute_gas_refill_locked_stablecoin_usd_from_full_target_guardrail() -> None:
    native_lamports = 100_000_000
    native_token_balance_usd = 16.8
    wallet_context = _build_wallet_context(
        native_lamports=native_lamports,
        native_token_balance_usd=native_token_balance_usd,
    )
    budget_snapshot, _cost_snapshot = _build_budget_and_cost_snapshots()

    with patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service.build_solana_gas_budget_snapshot",
        return_value=budget_snapshot,
    ):
        locked_stablecoin_usd = compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
            wallet_context=wallet_context,
        )

    expected_locked_usd = _expected_locked_usd_from_budget(
        budget_snapshot=budget_snapshot,
        native_token_balance_usd=native_token_balance_usd,
        native_lamports=native_lamports,
    )
    assert locked_stablecoin_usd == expected_locked_usd


def test_compute_gas_refill_locked_stablecoin_usd_uses_full_target_when_native_above_target() -> None:
    native_lamports = 600_000_000
    native_token_balance_usd = 100.0
    wallet_context = _build_wallet_context(
        native_lamports=native_lamports,
        native_token_balance_usd=native_token_balance_usd,
    )
    budget_snapshot, _cost_snapshot = _build_budget_and_cost_snapshots()

    with patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service.build_solana_gas_budget_snapshot",
        return_value=budget_snapshot,
    ):
        locked_stablecoin_usd = compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
            wallet_context=wallet_context,
        )

    expected_locked_usd = _expected_locked_usd_from_budget(
        budget_snapshot=budget_snapshot,
        native_token_balance_usd=native_token_balance_usd,
        native_lamports=native_lamports,
    )
    assert locked_stablecoin_usd == expected_locked_usd
    assert locked_stablecoin_usd > 0.0


def test_compute_gas_refill_locked_stablecoin_usd_zero_when_refill_target_is_zero() -> None:
    wallet_context = _build_wallet_context(
        native_lamports=100_000_000,
        native_token_balance_usd=16.8,
    )
    budget_snapshot, _cost_snapshot = _build_budget_and_cost_snapshots()
    budget_snapshot = TradingWalletMaintenanceSolanaGasBudgetSnapshot(
        max_open_positions=0,
        token_account_rent_lamports=budget_snapshot.token_account_rent_lamports,
        average_swap_fee_lamports=budget_snapshot.average_swap_fee_lamports,
        cycle_cost_lamports=0,
        refill_threshold_lamports=0,
        refill_target_lamports=0,
    )

    with patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service.build_solana_gas_budget_snapshot",
        return_value=budget_snapshot,
    ):
        locked_stablecoin_usd = compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
            wallet_context=wallet_context,
        )

    assert locked_stablecoin_usd == 0.0


def test_compute_net_deployable_cash_usd_subtracts_locked_total() -> None:
    locked_snapshot = MagicMock()
    locked_snapshot.gas_refill_locked_stablecoin_usd = 2.5
    wallet_context = _build_wallet_context(native_lamports=100_000_000, native_token_balance_usd=16.8)
    with patch(
        "src.core.trading.gasreserve.trading_gas_reserve_service.settings",
    ) as mock_settings, patch(
        "src.core.trading.gasreserve.trading_gas_reserve_service.resolve_gas_reserve_chain_handlers",
        return_value=[TradingGasReserveSolanaHandler(wallet_context=wallet_context)],
    ), patch(
        "src.core.trading.gasreserve.trading_gas_reserve_service._resolve_solana_wallet_context_for_live_gas_reserve",
        return_value=wallet_context,
    ), patch.object(
        TradingGasReserveSolanaHandler,
        "compute_gas_refill_locked_stablecoin_snapshot",
        return_value=locked_snapshot,
    ):
        mock_settings.TRADING_PAPER_MODE = False
        assert compute_total_gas_refill_locked_stablecoin_usd() == 2.5
        assert compute_net_deployable_cash_usd(13.76) == 11.26


def test_compute_total_gas_refill_locked_stablecoin_usd_paper_mode_returns_zero() -> None:
    with patch("src.core.trading.gasreserve.trading_gas_reserve_service.settings") as mock_settings:
        mock_settings.TRADING_PAPER_MODE = True
        assert compute_total_gas_refill_locked_stablecoin_usd() == 0.0


def test_build_solana_gas_refill_locked_breakdown_exposes_computed_amounts() -> None:
    native_lamports = 100_000_000
    native_token_balance_usd = 16.8
    wallet_context = _build_wallet_context(
        native_lamports=native_lamports,
        native_token_balance_usd=native_token_balance_usd,
    )
    budget_snapshot, _cost_snapshot = _build_budget_and_cost_snapshots()
    sol_usd_price = native_token_balance_usd / 0.1

    with patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service.build_solana_gas_budget_snapshot",
        return_value=budget_snapshot,
    ), patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service.settings",
    ) as mock_settings:
        mock_settings.TRADING_GAS_REFILL_TARGET_CYCLE_NUMBER = 16
        mock_settings.TRADING_GAS_MINIMUM_CYCLE_NUMBER = 4
        breakdown = build_solana_gas_refill_locked_breakdown(wallet_context=wallet_context)
        expected_locked_usd = compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
            wallet_context=wallet_context,
        )

    assert breakdown.max_open_positions == 10
    assert breakdown.refill_target_cycle_count == 16
    assert breakdown.refill_trigger_cycle_count == 4
    assert breakdown.per_position_cycle_cost_native_raw == 0.00353928
    assert breakdown.portfolio_cycle_cost_native_raw == 0.0353928
    assert breakdown.refill_target_budget_native_raw == 0.5662848
    assert breakdown.native_gas_balance_raw == 0.1
    assert breakdown.native_gas_balance_usd == 16.8
    assert breakdown.refill_trigger_threshold_native_raw == 0.1415712
    assert breakdown.per_position_cycle_cost_usd == round(0.00353928 * sol_usd_price, 2)
    assert breakdown.locked_stablecoin_usd == expected_locked_usd
    assert breakdown.locked_stablecoin_usd == breakdown.refill_target_budget_usd


def test_solana_wallet_auxiliary_assets_snapshot_includes_locked_and_rent() -> None:
    wallet_context = _build_wallet_context(native_lamports=100_000_000, native_token_balance_usd=16.8)
    budget_snapshot, _cost_snapshot = _build_budget_and_cost_snapshots()

    with patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service.build_solana_gas_budget_snapshot",
        return_value=budget_snapshot,
    ):
        snapshot = compute_solana_wallet_auxiliary_assets_snapshot(wallet_context=wallet_context)
        locked_snapshot = compute_solana_gas_refill_locked_stablecoin_snapshot(wallet_context=wallet_context)

    assert snapshot.blockchain_network == BlockchainNetwork.SOLANA
    assert snapshot.native_token_balance_usd == 16.8
    assert snapshot.recoverable_wallet_capital_usd == 1.5
    assert snapshot.gas_refill_locked_stablecoin_usd == locked_snapshot.gas_refill_locked_stablecoin_usd
    assert snapshot.gas_refill_locked_stablecoin_usd > 0.0
    assert snapshot.total_wallet_auxiliary_assets_usd == (
        snapshot.native_token_balance_usd
        + snapshot.gas_refill_locked_stablecoin_usd
        + snapshot.recoverable_wallet_capital_usd
    )
