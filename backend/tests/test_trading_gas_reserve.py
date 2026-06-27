from __future__ import annotations

from unittest.mock import patch

import pytest

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_helpers import (
    compute_cycle_cost_lamports,
    compute_per_position_cost_lamports,
    compute_reserve_lamports,
)
from src.core.trading.gasreserve.trading_gas_reserve_service import is_gas_reserve_sufficient_for_buy
from src.core.trading.trading_structures import TradingConfigurationError


def test_compute_per_position_cost_lamports() -> None:
    per_position_cost = compute_per_position_cost_lamports(
        token_account_rent_lamports=2_039_280,
        average_swap_fee_lamports=500_000,
    )
    assert per_position_cost == 2_039_280 + (3 * 500_000)


def test_compute_cycle_cost_lamports() -> None:
    cycle_cost = compute_cycle_cost_lamports(
        max_open_positions=10,
        token_account_rent_lamports=2_039_280,
        average_swap_fee_lamports=500_000,
    )
    assert cycle_cost == 10 * (2_039_280 + (3 * 500_000))


def test_compute_reserve_lamports() -> None:
    cycle_cost = 35_392_800
    assert compute_reserve_lamports(cycle_cost_lamports=cycle_cost, cycle_count=4) == cycle_cost * 4


def test_is_gas_reserve_sufficient_for_buy_paper_mode() -> None:
    with patch("src.core.trading.gasreserve.trading_gas_reserve_service.settings") as mock_settings:
        mock_settings.TRADING_PAPER_MODE = True
        assert is_gas_reserve_sufficient_for_buy(BlockchainNetwork.SOLANA) is True


def test_is_gas_reserve_sufficient_for_buy_when_balance_is_sufficient() -> None:
    with patch("src.core.trading.gasreserve.trading_gas_reserve_service.settings") as mock_settings:
        mock_settings.TRADING_PAPER_MODE = False
        with patch(
            "src.core.trading.gasreserve.trading_gas_reserve_service.is_solana_gas_reserve_sufficient_for_buy",
            return_value=True,
        ):
            assert is_gas_reserve_sufficient_for_buy(BlockchainNetwork.SOLANA) is True


def test_is_gas_reserve_sufficient_for_buy_when_balance_is_insufficient() -> None:
    with patch("src.core.trading.gasreserve.trading_gas_reserve_service.settings") as mock_settings:
        mock_settings.TRADING_PAPER_MODE = False
        with patch(
            "src.core.trading.gasreserve.trading_gas_reserve_service.is_solana_gas_reserve_sufficient_for_buy",
            return_value=False,
        ):
            assert is_gas_reserve_sufficient_for_buy(BlockchainNetwork.SOLANA) is False


def test_is_gas_reserve_sufficient_for_buy_when_blockchain_not_allowed() -> None:
    with patch("src.core.trading.gasreserve.trading_gas_reserve_service.settings") as mock_settings:
        mock_settings.TRADING_PAPER_MODE = False
        with pytest.raises(TradingConfigurationError):
            is_gas_reserve_sufficient_for_buy(BlockchainNetwork.BSC)


def test_is_solana_gas_reserve_sufficient_for_buy_when_balance_unavailable() -> None:
    with patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service.build_solana_gas_reserve_cost_snapshot",
    ) as mock_build_cost_snapshot, patch(
        "src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service._fetch_solana_native_balance_raw",
        return_value=None,
    ):
        from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_structures import (
            TradingGasReserveSolanaCostSnapshot,
        )

        mock_build_cost_snapshot.return_value = TradingGasReserveSolanaCostSnapshot(
            max_open_positions=10,
            token_account_rent_lamports=2_039_280,
            average_swap_fee_lamports=500_000,
            per_position_cost_lamports=2_039_280 + (3 * 500_000),
            cycle_cost_lamports=10 * (2_039_280 + (3 * 500_000)),
        )
        from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service import (
            is_solana_gas_reserve_sufficient_for_buy,
        )

        assert is_solana_gas_reserve_sufficient_for_buy() is False
