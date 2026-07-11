from __future__ import annotations

from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaStrategy


class _FakeSession:
    def add(self, _entity: object) -> None:
        return None

    def flush(self) -> None:
        return None


def test_update_strategy_execution_metrics_uses_on_chain_target_quantity() -> None:
    dca_strategy = AaveDcaStrategy(
        id=1,
        blockchain_network="avalanche",
        source_asset_symbol="USDC",
        source_asset_address="0xsource",
        source_asset_decimals=6,
        target_asset_symbol="BTC.b",
        target_asset_address="0xtarget",
        target_asset_decimals=8,
        binance_trading_pair="BTCUSDT",
        total_allocated_budget=6.9,
        total_planned_executions=10,
        amount_per_execution_order=0.69,
        slippage_tolerance=0.01,
        average_unit_price_elasticity_factor=1.0,
        current_cycle_index=0,
        previous_all_time_high_price=70000.0,
        previous_bull_market_amplitude_percentage=2.0,
        curve_flattening_factor=1.0,
        bear_market_bottom_multiplier=0.5,
        minimum_bull_market_multiplier=1.5,
        aave_estimated_annual_percentage_yield=0.03,
        realized_aave_yield_amount=0.0,
        last_yield_calculation_timestamp=__import__("datetime").datetime.now().astimezone(),
        strategy_start_date=__import__("datetime").datetime.now().astimezone(),
        strategy_end_date=__import__("datetime").datetime.now().astimezone(),
        strategy_status="ACTIVE",
        bypass_security_approval=True,
        available_dry_powder=0.0,
        total_deployed_amount=0.0,
        average_purchase_price=0.0,
        historical_backtest_payload={},
        created_at=__import__("datetime").datetime.now().astimezone(),
        updated_at=__import__("datetime").datetime.now().astimezone(),
    )

    strategy_dao = AaveDcaStrategyDao(_FakeSession())
    strategy_dao.update_strategy_execution_metrics(
        dca_strategy=dca_strategy,
        last_execution_source_amount=0.345,
        last_execution_target_asset_amount=5.37e-06,
        last_execution_reference_price=64082.0,
    )

    assert dca_strategy.total_deployed_amount == 0.345
    assert round(dca_strategy.average_purchase_price) == 64246
