from __future__ import annotations

import sqlalchemy as schema
from alembic import op as operations

revision = "20260512_0626"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    operations.create_table(
        "dca_strategies",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("blockchain_network", schema.String(length=32), nullable=False),
        schema.Column("source_asset_symbol", schema.String(length=24), nullable=False),
        schema.Column("source_asset_address", schema.String(length=128), nullable=False),
        schema.Column("source_asset_decimals", schema.Integer(), nullable=False),
        schema.Column("target_asset_symbol", schema.String(length=24), nullable=False),
        schema.Column("target_asset_address", schema.String(length=128), nullable=False),
        schema.Column("binance_trading_pair", schema.String(length=24), nullable=False),
        schema.Column("total_allocated_budget", schema.Float(), nullable=False),
        schema.Column("total_planned_executions", schema.Integer(), nullable=False),
        schema.Column("amount_per_execution_order", schema.Float(), nullable=False),
        schema.Column("slippage_tolerance", schema.Float(), nullable=False),
        schema.Column("average_unit_price_elasticity_factor", schema.Float(), nullable=False),
        schema.Column("current_cycle_index", schema.Integer(), nullable=False),
        schema.Column("previous_all_time_high_price", schema.Float(), nullable=False),
        schema.Column("previous_bull_market_amplitude_percentage", schema.Float(), nullable=False),
        schema.Column("curve_flattening_factor", schema.Float(), nullable=False),
        schema.Column("bear_market_bottom_multiplier", schema.Float(), nullable=False),
        schema.Column("minimum_bull_market_multiplier", schema.Float(), nullable=False),
        schema.Column("aave_estimated_annual_percentage_yield", schema.Float(), nullable=False),
        schema.Column("realized_aave_yield_amount", schema.Float(), nullable=False),
        schema.Column("last_yield_calculation_timestamp", schema.DateTime(timezone=True), nullable=False),
        schema.Column("strategy_start_date", schema.DateTime(timezone=True), nullable=False),
        schema.Column("strategy_end_date", schema.DateTime(timezone=True), nullable=False),
        schema.Column("strategy_status", schema.String(length=9), nullable=False),
        schema.Column("bypass_security_approval", schema.Boolean(), nullable=False),
        schema.Column("available_dry_powder", schema.Float(), nullable=False),
        schema.Column("total_deployed_amount", schema.Float(), nullable=False),
        schema.Column("average_purchase_price", schema.Float(), nullable=False),
        schema.Column("historical_backtest_payload", schema.JSON(), nullable=False),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
        schema.Column("updated_at", schema.DateTime(timezone=True), nullable=False),
    )

    operations.create_table(
        "dca_orders",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("strategy_id", schema.Integer(), schema.ForeignKey("dca_strategies.id"), nullable=False),
        schema.Column("planned_execution_date", schema.DateTime(timezone=True), nullable=False),
        schema.Column("planned_source_asset_amount", schema.Float(), nullable=False),
        schema.Column("executed_source_asset_amount", schema.Float(), nullable=True),
        schema.Column("executed_target_asset_amount", schema.Float(), nullable=True),
        schema.Column("order_status", schema.String(length=21), nullable=False),
        schema.Column("transaction_hash", schema.String(length=128), nullable=True),
        schema.Column("actual_execution_price", schema.Float(), nullable=True),
        schema.Column("executed_at", schema.DateTime(timezone=True), nullable=True),
        schema.Column("allocation_decision_description", schema.String(length=128), nullable=True),
    )

    operations.create_table(
        "trading_evaluations",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("token_symbol", schema.String(length=24), nullable=False),
        schema.Column("blockchain_network", schema.String(length=32), nullable=False),
        schema.Column("token_address", schema.String(length=128), nullable=False),
        schema.Column("pair_address", schema.String(length=128), nullable=False),
        schema.Column("price_usd", schema.Float(), nullable=False),
        schema.Column("price_native", schema.Float(), nullable=False),
        schema.Column("evaluated_at", schema.DateTime(timezone=True), nullable=False),
        schema.Column("candidate_rank", schema.Integer(), nullable=False),
        schema.Column("quality_score", schema.Float(), nullable=False),
        schema.Column("ai_adjusted_quality_score", schema.Float(), nullable=False),
        schema.Column("ai_probability_take_profit_before_stop_loss", schema.Float(), nullable=False),
        schema.Column("ai_quality_score_delta", schema.Float(), nullable=False),
        schema.Column("token_age_hours", schema.Float(), nullable=False),
        schema.Column("volume_m5_usd", schema.Float(), nullable=False),
        schema.Column("volume_h1_usd", schema.Float(), nullable=False),
        schema.Column("volume_h6_usd", schema.Float(), nullable=False),
        schema.Column("volume_h24_usd", schema.Float(), nullable=False),
        schema.Column("liquidity_usd", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_m5", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_h1", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_h6", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_h24", schema.Float(), nullable=False),
        schema.Column("transaction_count_m5", schema.Integer(), nullable=False),
        schema.Column("transaction_count_h1", schema.Integer(), nullable=False),
        schema.Column("transaction_count_h6", schema.Integer(), nullable=False),
        schema.Column("transaction_count_h24", schema.Integer(), nullable=False),
        schema.Column("buy_to_sell_ratio", schema.Float(), nullable=False),
        schema.Column("market_cap_usd", schema.Float(), nullable=False),
        schema.Column("fully_diluted_valuation_usd", schema.Float(), nullable=False),
        schema.Column("dexscreener_boost", schema.Float(), nullable=False),
        schema.Column("execution_decision", schema.String(length=16), nullable=False),
        schema.Column("sizing_multiplier", schema.Float(), nullable=False),
        schema.Column("order_notional_value_usd", schema.Float(), nullable=False),
        schema.Column("free_cash_before_execution_usd", schema.Float(), nullable=False),
        schema.Column("free_cash_after_execution_usd", schema.Float(), nullable=False),
        schema.Column("shadow_intelligence_snapshot", schema.JSON(), nullable=False),
        schema.Column("raw_dexscreener_payload", schema.JSON(), nullable=False),
        schema.Column("raw_configuration_settings", schema.JSON(), nullable=False),
    )

    operations.create_table(
        "trading_portfolio_snapshots",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("total_equity_value", schema.Float(), nullable=False),
        schema.Column("available_cash_balance", schema.Float(), nullable=False),
        schema.Column("active_holdings_value", schema.Float(), nullable=False),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
    )

    operations.create_table(
        "trading_shadowing_probes",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("token_symbol", schema.String(length=24), nullable=False),
        schema.Column("blockchain_network", schema.String(length=32), nullable=False),
        schema.Column("token_address", schema.String(length=128), nullable=False),
        schema.Column("pair_address", schema.String(length=128), nullable=False),
        schema.Column("dex_id", schema.String(length=32), nullable=False),
        schema.Column("entry_price_usd", schema.Float(), nullable=False),
        schema.Column("candidate_rank", schema.Integer(), nullable=False),
        schema.Column("quality_score", schema.Float(), nullable=False),
        schema.Column("token_age_hours", schema.Float(), nullable=False),
        schema.Column("volume_m5_usd", schema.Float(), nullable=False),
        schema.Column("volume_h1_usd", schema.Float(), nullable=False),
        schema.Column("volume_h6_usd", schema.Float(), nullable=False),
        schema.Column("volume_h24_usd", schema.Float(), nullable=False),
        schema.Column("liquidity_usd", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_m5", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_h1", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_h6", schema.Float(), nullable=False),
        schema.Column("price_change_percentage_h24", schema.Float(), nullable=False),
        schema.Column("transaction_count_m5", schema.Integer(), nullable=False),
        schema.Column("transaction_count_h1", schema.Integer(), nullable=False),
        schema.Column("transaction_count_h6", schema.Integer(), nullable=False),
        schema.Column("transaction_count_h24", schema.Integer(), nullable=False),
        schema.Column("buy_to_sell_ratio", schema.Float(), nullable=False),
        schema.Column("market_cap_usd", schema.Float(), nullable=False),
        schema.Column("fully_diluted_valuation_usd", schema.Float(), nullable=False),
        schema.Column("dexscreener_boost", schema.Float(), nullable=False),
        schema.Column("order_notional_value_usd", schema.Float(), nullable=False),
        schema.Column("probed_at", schema.DateTime(timezone=True), nullable=False),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
    )

    operations.create_table(
        "trading_positions",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("evaluation_id", schema.Integer(), schema.ForeignKey("trading_evaluations.id"), nullable=False),
        schema.Column("token_symbol", schema.String(length=24), nullable=False),
        schema.Column("blockchain_network", schema.String(length=32), nullable=False),
        schema.Column("token_address", schema.String(length=128), nullable=False),
        schema.Column("pair_address", schema.String(length=128), nullable=False),
        schema.Column("dex_id", schema.String(length=32), nullable=False),
        schema.Column("open_quantity", schema.Float(), nullable=False),
        schema.Column("current_quantity", schema.Float(), nullable=False),
        schema.Column("entry_price", schema.Float(), nullable=False),
        schema.Column("take_profit_tier_1_price", schema.Float(), nullable=False),
        schema.Column("take_profit_tier_2_price", schema.Float(), nullable=False),
        schema.Column("stop_loss_price", schema.Float(), nullable=False),
        schema.Column("position_phase", schema.String(length=7), nullable=False),
        schema.Column("opened_at", schema.DateTime(timezone=True), nullable=False),
        schema.Column("updated_at", schema.DateTime(timezone=True), nullable=False),
        schema.Column("closed_at", schema.DateTime(timezone=True), nullable=True),
    )

    operations.create_table(
        "trading_trades",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("evaluation_id", schema.Integer(), schema.ForeignKey("trading_evaluations.id"), nullable=False),
        schema.Column("trade_side", schema.String(length=4), nullable=False),
        schema.Column("token_symbol", schema.String(length=24), nullable=False),
        schema.Column("blockchain_network", schema.String(length=32), nullable=False),
        schema.Column("execution_price", schema.Float(), nullable=False),
        schema.Column("execution_quantity", schema.Float(), nullable=False),
        schema.Column("transaction_fee", schema.Float(), nullable=False),
        schema.Column("realized_profit_and_loss", schema.Float(), nullable=True),
        schema.Column("execution_status", schema.String(length=5), nullable=False),
        schema.Column("token_address", schema.String(length=128), nullable=False),
        schema.Column("pair_address", schema.String(length=128), nullable=False),
        schema.Column("dex_id", schema.String(length=32), nullable=False),
        schema.Column("transaction_hash", schema.String(length=128), nullable=True),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
    )

    operations.create_table(
        "trading_shadowing_verdicts",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("probe_id", schema.Integer(), schema.ForeignKey("trading_shadowing_probes.id"), nullable=False),
        schema.Column("take_profit_tier_1_price", schema.Float(), nullable=False),
        schema.Column("take_profit_tier_2_price", schema.Float(), nullable=False),
        schema.Column("stop_loss_price", schema.Float(), nullable=False),
        schema.Column("take_profit_tier_1_hit_at", schema.DateTime(timezone=True), nullable=True),
        schema.Column("take_profit_tier_2_hit_at", schema.DateTime(timezone=True), nullable=True),
        schema.Column("stop_loss_hit_at", schema.DateTime(timezone=True), nullable=True),
        schema.Column("exit_reason", schema.String(length=64), nullable=True),
        schema.Column("realized_pnl_percentage", schema.Float(), nullable=True),
        schema.Column("realized_pnl_usd", schema.Float(), nullable=True),
        schema.Column("holding_duration_minutes", schema.Float(), nullable=True),
        schema.Column("is_profitable", schema.Boolean(), nullable=True),
        schema.Column("resolved_at", schema.DateTime(timezone=True), nullable=True),
        schema.Column("created_at", schema.DateTime(timezone=True), nullable=False),
    )

    operations.create_table(
        "trading_outcomes",
        schema.Column("id", schema.Integer(), primary_key=True, autoincrement=True, nullable=False),
        schema.Column("evaluation_id", schema.Integer(), schema.ForeignKey("trading_evaluations.id"), nullable=False),
        schema.Column("trade_id", schema.Integer(), schema.ForeignKey("trading_trades.id"), nullable=False),
        schema.Column("exit_reason", schema.String(length=64), nullable=False),
        schema.Column("realized_profit_and_loss_percentage", schema.Float(), nullable=False),
        schema.Column("realized_profit_and_loss_usd", schema.Float(), nullable=False),
        schema.Column("holding_duration_minutes", schema.Float(), nullable=False),
        schema.Column("is_profitable", schema.Boolean(), nullable=False),
        schema.Column("occurred_at", schema.DateTime(timezone=True), nullable=False),
    )

    operations.create_index("ix_trading_evaluations_pair_address", "trading_evaluations", ["pair_address"])
    operations.create_index("ix_trading_evaluations_token_address", "trading_evaluations", ["token_address"])
    operations.create_index("ix_trading_evaluations_token_symbol", "trading_evaluations", ["token_symbol"])
    operations.create_index("ix_trading_outcomes_evaluation_id", "trading_outcomes", ["evaluation_id"])
    operations.create_index("ix_trading_positions_token_symbol", "trading_positions", ["token_symbol"])
    operations.create_index("ix_trading_shadowing_probes_pair_address", "trading_shadowing_probes", ["pair_address"])
    operations.create_index("ix_trading_shadowing_probes_token_address", "trading_shadowing_probes", ["token_address"])
    operations.create_index("ix_trading_shadowing_probes_token_symbol", "trading_shadowing_probes", ["token_symbol"])
    operations.create_index(
        "ix_trading_shadowing_verdicts_probe_id",
        "trading_shadowing_verdicts",
        ["probe_id"],
        unique=True,
    )
    operations.create_index("ix_trading_trades_token_symbol", "trading_trades", ["token_symbol"])
    operations.create_index("ix_trading_trades_trade_side", "trading_trades", ["trade_side"])


def downgrade() -> None:
    operations.drop_index("ix_trading_trades_trade_side", table_name="trading_trades")
    operations.drop_index("ix_trading_trades_token_symbol", table_name="trading_trades")
    operations.drop_index("ix_trading_shadowing_verdicts_probe_id", table_name="trading_shadowing_verdicts")
    operations.drop_index("ix_trading_shadowing_probes_token_symbol", table_name="trading_shadowing_probes")
    operations.drop_index("ix_trading_shadowing_probes_token_address", table_name="trading_shadowing_probes")
    operations.drop_index("ix_trading_shadowing_probes_pair_address", table_name="trading_shadowing_probes")
    operations.drop_index("ix_trading_positions_token_symbol", table_name="trading_positions")
    operations.drop_index("ix_trading_outcomes_evaluation_id", table_name="trading_outcomes")
    operations.drop_index("ix_trading_evaluations_token_symbol", table_name="trading_evaluations")
    operations.drop_index("ix_trading_evaluations_token_address", table_name="trading_evaluations")
    operations.drop_index("ix_trading_evaluations_pair_address", table_name="trading_evaluations")

    operations.drop_table("trading_outcomes")
    operations.drop_table("trading_shadowing_verdicts")
    operations.drop_table("trading_trades")
    operations.drop_table("trading_positions")
    operations.drop_table("trading_shadowing_probes")
    operations.drop_table("trading_portfolio_snapshots")
    operations.drop_table("trading_evaluations")
    operations.drop_table("dca_orders")
    operations.drop_table("dca_strategies")
