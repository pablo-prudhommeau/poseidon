from __future__ import annotations

import asyncio
from datetime import datetime

from src.core.aavesentinel.notification.aave_sentinel_notification_service import AaveSentinelNotificationService
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelNonTradingMovementSource,
    AaveSentinelNonTradingPeriodSourceBreakdown,
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionSnapshot,
    AaveSentinelReserveInterestBreakdown,
    AaveSentinelStrategy,
    AaveSentinelStrategyCycleSummary,
    AaveSentinelStrategyKind,
    AaveSentinelUnallocatedWealthMovement,
)


def test_build_balance_sheet_section_lines_uses_dont_apy_and_coded_global_result() -> None:
    notification_service = AaveSentinelNotificationService()
    balance_sheet_section_lines = notification_service._build_balance_sheet_section_lines(
        performance_summary=AaveSentinelPerformanceSummary(
            global_pnl_usd=2400.0,
            total_trading_pnl_usd=1965.0,
            cumulative_net_interest_usd=435.0,
            strategy_legs_pnl_usd=2350.0,
            unallocated_wealth_pnl_usd=50.0,
            is_available=True,
        ),
        capital_flow_summary=AaveSentinelCapitalFlowSummary(net_capital_deployed_usd=8000.0),
        format_monetary_values=lambda amount_in_usd: f"${amount_in_usd:.2f}",
    )
    joined_balance_sheet_section: str = "\n".join(balance_sheet_section_lines)
    assert "📋 Mouvements :" not in joined_balance_sheet_section
    assert "Intérêts AAVE cumulés" not in joined_balance_sheet_section
    assert "🏦 Dont APY : <code>$435.00</code>" in joined_balance_sheet_section
    assert "💵 PnL : 🚀 <code>$2400.00 (30.00%)</code>" in joined_balance_sheet_section


def test_build_strategy_cycle_entry_exit_price_line_for_closed_and_open_cycles() -> None:
    notification_service = AaveSentinelNotificationService()
    closed_cycle_line = notification_service._build_strategy_cycle_entry_exit_price_line(
        strategy_cycle=AaveSentinelStrategyCycleSummary(
            kind=AaveSentinelStrategyKind.SHORT,
            opened_at_timestamp_seconds=1,
            opening_block_number=1,
            entry_main_asset_price_usd=63000.0,
            exit_main_asset_price_usd=64800.0,
        ),
    )
    open_cycle_without_snapshot_line = notification_service._build_strategy_cycle_entry_exit_price_line(
        strategy_cycle=AaveSentinelStrategyCycleSummary(
            kind=AaveSentinelStrategyKind.SHORT,
            main_asset_symbol="BTC.b",
            opened_at_timestamp_seconds=1,
            opening_block_number=1,
            is_open=True,
            entry_main_asset_price_usd=63000.0,
            exit_main_asset_price_usd=None,
        ),
    )
    open_cycle_with_snapshot_line = notification_service._build_strategy_cycle_entry_exit_price_line(
        strategy_cycle=AaveSentinelStrategyCycleSummary(
            kind=AaveSentinelStrategyKind.SHORT,
            main_asset_symbol="BTC.b",
            opened_at_timestamp_seconds=1,
            opening_block_number=1,
            is_open=True,
            entry_main_asset_price_usd=63000.0,
            exit_main_asset_price_usd=None,
        ),
        position_snapshot=AaveSentinelPositionSnapshot(
            health_factor=1.5,
            total_collateral_usd=1000.0,
            total_debt_usd=500.0,
            strategies=[
                AaveSentinelStrategy(
                    kind=AaveSentinelStrategyKind.SHORT,
                    main_asset_symbol="BTC.b",
                    main_asset_price_usd=64123.0,
                    liquidation_price_usd=70000.0,
                    leverage=2.0,
                    collateral_usd=1000.0,
                    debt_usd=500.0,
                ),
            ],
        ),
    )
    missing_entry_line = notification_service._build_strategy_cycle_entry_exit_price_line(
        strategy_cycle=AaveSentinelStrategyCycleSummary(
            kind=AaveSentinelStrategyKind.SHORT,
            opened_at_timestamp_seconds=1,
            opening_block_number=1,
            entry_main_asset_price_usd=0.0,
        ),
    )
    assert closed_cycle_line == "    💸 Entrée → sortie : <code>$63,000.00 → $64,800.00</code>"
    assert open_cycle_without_snapshot_line == "    💸 Entrée : <code>$63,000.00</code>"
    assert open_cycle_with_snapshot_line == (
        "    💸 Entrée → actuel : <code>$63,000.00 → $64,123.00</code>"
    )
    assert missing_entry_line is None


def test_format_pnl_detail_message_groups_non_trading_period_with_blank_lines() -> None:
    async def run_test() -> None:
        notification_service = AaveSentinelNotificationService()

        async def resolve_exchange_rate() -> float:
            return 1.0

        notification_service._fetch_usd_eur_exchange_rate = resolve_exchange_rate
        formatted_message = await notification_service.format_pnl_detail_message(
            performance_summary=AaveSentinelPerformanceSummary(
                global_pnl_usd=100.0,
                total_trading_pnl_usd=60.0,
                cumulative_supply_interest_usd=50.0,
                cumulative_borrow_interest_usd=10.0,
                cumulative_net_interest_usd=40.0,
                interest_breakdowns=[
                    AaveSentinelReserveInterestBreakdown(
                        asset_symbol="USDC",
                        supply_interest_usd=50.0,
                        borrow_interest_usd=10.0,
                        net_interest_usd=40.0,
                    ),
                ],
                strategy_cycles=[
                    AaveSentinelStrategyCycleSummary(
                        kind=AaveSentinelStrategyKind.SHORT,
                        main_asset_symbol="BTC.b",
                        leverage=2.0,
                        opened_at_timestamp_seconds=1_700_086_400,
                        closed_at_timestamp_seconds=1_700_172_800,
                        opening_block_number=1,
                        closing_block_number=2,
                        gross_pnl_usd=60.0,
                        entry_main_asset_price_usd=63000.0,
                        exit_main_asset_price_usd=64000.0,
                        absorbed_source_breakdowns=[
                            AaveSentinelNonTradingPeriodSourceBreakdown(
                                source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
                                pnl_usd=8.50,
                            ),
                        ],
                    ),
                    AaveSentinelStrategyCycleSummary(
                        kind=AaveSentinelStrategyKind.LONG,
                        main_asset_symbol="BTC.b",
                        leverage=1.5,
                        opened_at_timestamp_seconds=1_700_200_000,
                        closed_at_timestamp_seconds=1_700_300_000,
                        opening_block_number=3,
                        closing_block_number=4,
                        gross_pnl_usd=20.0,
                        entry_main_asset_price_usd=64000.0,
                        exit_main_asset_price_usd=65000.0,
                        is_open=True,
                    ),
                ],
                unallocated_wealth_movements=[
                    AaveSentinelUnallocatedWealthMovement(
                        source=AaveSentinelNonTradingMovementSource.SLIPPAGE,
                        started_at_timestamp_seconds=1_700_000_000,
                        ended_at_timestamp_seconds=1_700_086_400,
                        pnl_usd=-58.38,
                    ),
                    AaveSentinelUnallocatedWealthMovement(
                        source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
                        started_at_timestamp_seconds=1_700_000_000,
                        ended_at_timestamp_seconds=1_700_086_400,
                        pnl_usd=12.50,
                    ),
                    AaveSentinelUnallocatedWealthMovement(
                        source=AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP,
                        started_at_timestamp_seconds=1_700_000_000,
                        ended_at_timestamp_seconds=1_700_086_400,
                        pnl_usd=-11.29,
                    ),
                    AaveSentinelUnallocatedWealthMovement(
                        source=AaveSentinelNonTradingMovementSource.GAS_FEES,
                        started_at_timestamp_seconds=1_700_000_000,
                        ended_at_timestamp_seconds=1_700_086_400,
                        pnl_usd=-1.00,
                    ),
                ],
                unallocated_wealth_pnl_usd=-58.17,
                is_available=True,
            ),
        )
        assert formatted_message.count("💤 <b>Hors trading</b>") == 1
        assert "      • Brut :" in formatted_message
        assert "      • Dont intérêts :" in formatted_message
        assert "      • Dont conversion :" in formatted_message
        assert "      • Dont écart valo :" in formatted_message
        assert "      • Dont gas :" in formatted_message
        assert "    📊 PnL :" in formatted_message
        assert "APY borrow" in formatted_message
        assert "APY supply" in formatted_message
        assert "APY net" in formatted_message
        assert "◦ Supply :" in formatted_message
        assert "◦ Borrow :" in formatted_message
        assert "◦ Net :" in formatted_message
        assert "    💸 Entrée → sortie" in formatted_message
        assert "📋 Mouvements :" not in formatted_message
        assert "<b>Bilan</b>" not in formatted_message
        assert "Dont APY" not in formatted_message
        assert "Résultat :" not in formatted_message
        assert "PnL latent :" not in formatted_message
        assert "<b>Intérêts AAVE</b>" in formatted_message
        assert "<b>Mouvements</b>" in formatted_message
        assert formatted_message.index("<b>Intérêts AAVE</b>") < formatted_message.index("<b>Mouvements</b>")
        assert "✅" not in formatted_message
        assert "⏳" not in formatted_message
        assert "📉 <b>SHORT</b> BTC.b" in formatted_message
        assert "📈 <b>LONG</b> BTC.b" in formatted_message
        assert "$-10.00" in formatted_message
        hors_trading_started_at_label: str = (
            datetime.fromtimestamp(1_700_000_000).astimezone().strftime("%d/%m/%Y %H:%M")
        )
        hors_trading_ended_at_label: str = (
            datetime.fromtimestamp(1_700_086_400).astimezone().strftime("%d/%m/%Y %H:%M")
        )
        assert (
            f"    📅 {hors_trading_started_at_label} → {hors_trading_ended_at_label}"
            in formatted_message
        )
        hors_trading_index: int = formatted_message.index("💤 <b>Hors trading</b>")
        short_index: int = formatted_message.index("📉 <b>SHORT</b>")
        long_index: int = formatted_message.index("📈 <b>LONG</b>")
        assert hors_trading_index < short_index < long_index
        assert "\n\n📉 <b>SHORT</b>" in formatted_message
        assert "\n\n📈 <b>LONG</b>" in formatted_message

    asyncio.run(run_test())


def test_format_pnl_detail_message_shows_absorbed_dont_lines_and_dominant_asset() -> None:
    async def run_test() -> None:
        notification_service = AaveSentinelNotificationService()

        async def resolve_exchange_rate() -> float:
            return 1.0

        notification_service._fetch_usd_eur_exchange_rate = resolve_exchange_rate
        formatted_message = await notification_service.format_pnl_detail_message(
            performance_summary=AaveSentinelPerformanceSummary(
                global_pnl_usd=100.0,
                total_trading_pnl_usd=60.0,
                cumulative_net_interest_usd=40.0,
                strategy_cycles=[
                    AaveSentinelStrategyCycleSummary(
                        kind=AaveSentinelStrategyKind.SHORT,
                        main_asset_symbol="BTC.b",
                        leverage=2.0,
                        opened_at_timestamp_seconds=1_700_086_400,
                        closed_at_timestamp_seconds=1_700_172_800,
                        opening_block_number=1,
                        closing_block_number=2,
                        gross_pnl_usd=60.0,
                        entry_main_asset_price_usd=63000.0,
                        exit_main_asset_price_usd=64000.0,
                        absorbed_source_breakdowns=[
                            AaveSentinelNonTradingPeriodSourceBreakdown(
                                source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
                                pnl_usd=4.20,
                            ),
                            AaveSentinelNonTradingPeriodSourceBreakdown(
                                source=AaveSentinelNonTradingMovementSource.SLIPPAGE,
                                pnl_usd=-1.25,
                            ),
                            AaveSentinelNonTradingPeriodSourceBreakdown(
                                source=AaveSentinelNonTradingMovementSource.GAS_FEES,
                                pnl_usd=-0.80,
                            ),
                        ],
                    ),
                ],
                unallocated_wealth_movements=[
                    AaveSentinelUnallocatedWealthMovement(
                        source=AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP,
                        started_at_timestamp_seconds=1_700_000_000,
                        ended_at_timestamp_seconds=1_700_086_400,
                        pnl_usd=-65.09,
                        dominant_asset_symbol="EURC",
                    ),
                    AaveSentinelUnallocatedWealthMovement(
                        source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
                        started_at_timestamp_seconds=1_700_000_000,
                        ended_at_timestamp_seconds=1_700_086_400,
                        pnl_usd=6.72,
                    ),
                ],
                unallocated_wealth_pnl_usd=-58.37,
                is_available=True,
            ),
        )
        assert "      • Brut :" in formatted_message
        assert "      • Dont écart valo (EURC) :" in formatted_message
        assert "      • Dont conversion :" in formatted_message
        assert "      • Dont gas :" in formatted_message
        assert "      • Dont intérêts :" in formatted_message
        assert "◦ Perte sur swap :" not in formatted_message
        assert "◦ Dont" not in formatted_message
        short_block: str = formatted_message[formatted_message.index("📉 <b>SHORT</b>"):]
        assert "      • Brut : <code>57.85 € ($57.85)</code>" in short_block

    asyncio.run(run_test())


def test_format_pnl_detail_message_folds_fully_overlapping_hors_trading_into_strategy() -> None:
    async def run_test() -> None:
        notification_service = AaveSentinelNotificationService()

        async def resolve_exchange_rate() -> float:
            return 1.0

        notification_service._fetch_usd_eur_exchange_rate = resolve_exchange_rate
        latest_aave_position_snapshot_at = datetime(2026, 7, 19, 11, 44, 0).astimezone()
        formatted_message = await notification_service.format_pnl_detail_message(
            performance_summary=AaveSentinelPerformanceSummary(
                global_pnl_usd=-0.03,
                total_trading_pnl_usd=-0.03,
                strategy_legs_pnl_usd=-0.62,
                unallocated_wealth_pnl_usd=0.62,
                strategy_cycles=[
                    AaveSentinelStrategyCycleSummary(
                        kind=AaveSentinelStrategyKind.LONG,
                        main_asset_symbol="BTC.b",
                        leverage=1.0,
                        opened_at_timestamp_seconds=1_700_000_000,
                        closed_at_timestamp_seconds=None,
                        opening_block_number=1,
                        gross_pnl_usd=-0.01,
                        entry_main_asset_price_usd=64289.0,
                        is_open=True,
                    ),
                    AaveSentinelStrategyCycleSummary(
                        kind=AaveSentinelStrategyKind.SHORT,
                        main_asset_symbol="BTC.b",
                        leverage=1.12,
                        opened_at_timestamp_seconds=1_700_086_400,
                        closed_at_timestamp_seconds=1_700_090_000,
                        opening_block_number=2,
                        closing_block_number=3,
                        gross_pnl_usd=-0.62,
                        entry_main_asset_price_usd=62142.0,
                        exit_main_asset_price_usd=61848.0,
                    ),
                ],
                unallocated_wealth_movements=[
                    AaveSentinelUnallocatedWealthMovement(
                        source=AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP,
                        started_at_timestamp_seconds=1_700_086_400,
                        ended_at_timestamp_seconds=1_700_089_000,
                        pnl_usd=0.62,
                    ),
                ],
                is_available=True,
            ),
            position_snapshot=AaveSentinelPositionSnapshot(
                health_factor=1.5,
                total_collateral_usd=1000.0,
                total_debt_usd=500.0,
                captured_at=latest_aave_position_snapshot_at,
                strategies=[
                    AaveSentinelStrategy(
                        kind=AaveSentinelStrategyKind.LONG,
                        main_asset_symbol="BTC.b",
                        main_asset_price_usd=65000.0,
                        liquidation_price_usd=50000.0,
                        leverage=1.0,
                        collateral_usd=1000.0,
                        debt_usd=500.0,
                    ),
                ],
            ),
        )
        assert "💤 <b>Hors trading</b>" not in formatted_message
        assert "📉 <b>SHORT</b> BTC.b" in formatted_message
        assert "…" not in formatted_message
        open_cycle_opened_at_label: str = (
            datetime.fromtimestamp(1_700_000_000).astimezone().strftime("%d/%m/%Y %H:%M")
        )
        open_cycle_snapshot_at_label: str = (
            latest_aave_position_snapshot_at.astimezone().strftime("%d/%m/%Y %H:%M")
        )
        assert (
            f"    📅 {open_cycle_opened_at_label} → {open_cycle_snapshot_at_label}"
            in formatted_message
        )
        assert "    💸 Entrée → actuel : <code>$64,289.00 → $65,000.00</code>" in formatted_message
        short_block_index: int = formatted_message.index("📉 <b>SHORT</b> BTC.b")
        short_block: str = formatted_message[short_block_index:]
        assert "📊 PnL : <code>0.00 € ($0.00)</code>" in short_block
        assert "      • Brut : <code>-0.62 € ($-0.62)</code>" in short_block
        assert "      • Dont écart valo : <code>0.62 € ($0.62)</code>" in short_block

    asyncio.run(run_test())


def test_format_pnl_detail_message_pages_uses_untitled_movement_continuations() -> None:
    async def run_test() -> None:
        notification_service = AaveSentinelNotificationService()

        async def resolve_exchange_rate() -> float:
            return 1.0

        notification_service._fetch_usd_eur_exchange_rate = resolve_exchange_rate
        strategy_cycles: list[AaveSentinelStrategyCycleSummary] = [
            AaveSentinelStrategyCycleSummary(
                kind=AaveSentinelStrategyKind.SHORT,
                main_asset_symbol="BTC.b",
                leverage=2.0,
                opened_at_timestamp_seconds=1_700_000_000 + (cycle_index * 100_000),
                closed_at_timestamp_seconds=1_700_000_000 + (cycle_index * 100_000) + 50_000,
                opening_block_number=cycle_index + 1,
                closing_block_number=cycle_index + 2,
                gross_pnl_usd=10.0 + cycle_index,
                entry_main_asset_price_usd=60000.0,
                exit_main_asset_price_usd=61000.0,
            )
            for cycle_index in range(20)
        ]
        formatted_pages = await notification_service.format_pnl_detail_message_pages(
            performance_summary=AaveSentinelPerformanceSummary(
                global_pnl_usd=100.0,
                cumulative_net_interest_usd=40.0,
                strategy_cycles=strategy_cycles,
                is_available=True,
            ),
        )
        assert len(formatted_pages) > 1
        assert "<b>Bilan</b>" not in formatted_pages[0]
        assert "<b>Intérêts AAVE</b>" in formatted_pages[0]
        assert "<b>Mouvements</b>" in formatted_pages[0]
        assert formatted_pages[0].index("<b>Intérêts AAVE</b>") < formatted_pages[0].index(
            "<b>Mouvements</b>"
        )
        for continuation_page in formatted_pages[1:]:
            assert "<b>Bilan</b>" not in continuation_page
            assert "<b>Intérêts AAVE</b>" not in continuation_page
            assert "<b>Mouvements</b>" not in continuation_page
            assert "📄 Page" not in continuation_page
            assert "📉 <b>SHORT</b> BTC.b" in continuation_page

    asyncio.run(run_test())


def test_format_notification_message_always_shows_strategies_section() -> None:
    async def run_test() -> None:
        notification_service = AaveSentinelNotificationService()

        async def resolve_exchange_rate() -> float:
            return 1.0

        notification_service._fetch_usd_eur_exchange_rate = resolve_exchange_rate
        formatted_message = await notification_service.format_notification_message(
            position_snapshot=AaveSentinelPositionSnapshot(
                health_factor=1.5,
                total_collateral_usd=0.0,
                total_debt_usd=0.0,
                assets=[],
                strategies=[],
            ),
            capital_flow_summary=AaveSentinelCapitalFlowSummary(),
            performance_summary=AaveSentinelPerformanceSummary(is_available=True),
        )
        assert "Compte" in formatted_message
        assert "Statut du compte" not in formatted_message
        assert "Bilan" not in formatted_message
        assert "Stratégies" in formatted_message
        assert "Aucune stratégie en cours" in formatted_message
        assert "Positions AAVE" in formatted_message
        assert "📈 Collatéral (" in formatted_message
        assert "📉 Dette (" in formatted_message
        assert "💼 Wallet (" in formatted_message
        assert "<b>💼 Wallet" not in formatted_message
        positions_section_start: int = formatted_message.index("Positions AAVE")
        performance_section_start: int = formatted_message.index("Performance")
        positions_section: str = formatted_message[positions_section_start:performance_section_start]
        assert "💼 Wallet (" in positions_section
        assert "\nTotal" not in formatted_message
        assert "<i>Aucun</i>" in formatted_message
        assert "calcul…" not in formatted_message
        assert "💵 PnL :" in formatted_message
        assert "🚀" in formatted_message
        assert "0.00 € · $0.00" in formatted_message

    asyncio.run(run_test())
