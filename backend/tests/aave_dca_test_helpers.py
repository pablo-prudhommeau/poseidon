from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.core.aavedca.aave_dca_helpers import create_empty_pipeline_operations
from src.core.aavedca.aave_dca_structures import AaveDcaOrderStatus, AaveDcaStrategyStatus
from src.persistence.database_session_manager import DatabaseBaseModel
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

WALLET_ADDRESS: str = "0xD404a0000000000000000000000000000003f75B"
POOL_ADDRESS: str = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
USDC_ADDRESS: str = "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E"
BTCB_ADDRESS: str = "0x152b9d0FdC40C096757F570A51E494bd4b943E50"


def build_aave_dca_database_session() -> Session:
    database_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    DatabaseBaseModel.metadata.create_all(database_engine, tables=[AaveDcaStrategy.__table__, AaveDcaOrder.__table__])
    return Session(database_engine, expire_on_commit=False)


def build_aave_dca_strategy(strategy_status: AaveDcaStrategyStatus, blockchain_network: str) -> AaveDcaStrategy:
    current_local_time: datetime = datetime.now().astimezone()
    return AaveDcaStrategy(
        blockchain_network=blockchain_network,
        source_asset_symbol="USDC",
        source_asset_address=USDC_ADDRESS,
        source_asset_decimals=6,
        target_asset_symbol="BTC.b",
        target_asset_address=BTCB_ADDRESS,
        target_asset_decimals=8,
        binance_trading_pair="BTCUSDT",
        total_allocated_budget=1000.0,
        total_planned_executions=20,
        amount_per_execution_order=50.0,
        slippage_tolerance=0.01,
        average_unit_price_elasticity_factor=10.0,
        current_cycle_index=5,
        previous_all_time_high_price=125000.0,
        previous_bull_market_amplitude_percentage=680.0,
        curve_flattening_factor=3.0,
        bear_market_bottom_multiplier=0.3,
        minimum_bull_market_multiplier=1.2,
        aave_estimated_annual_percentage_yield=0.05,
        realized_aave_yield_amount=0.0,
        last_yield_calculation_timestamp=current_local_time,
        strategy_start_date=current_local_time,
        strategy_end_date=current_local_time + timedelta(days=10),
        strategy_status=strategy_status,
        bypass_security_approval=True,
        available_dry_powder=0.0,
        total_deployed_amount=0.0,
        average_purchase_price=0.0,
        historical_backtest_payload={},
        created_at=current_local_time,
        updated_at=current_local_time,
    )


def build_aave_dca_order(
        strategy_id: int,
        order_status: AaveDcaOrderStatus,
        suspension_reason: Optional[str],
) -> AaveDcaOrder:
    return AaveDcaOrder(
        strategy_id=strategy_id,
        planned_execution_date=datetime.now().astimezone(),
        planned_source_asset_amount=50.0,
        executed_source_asset_amount=50.0,
        executed_target_asset_amount=None,
        order_status=order_status,
        actual_execution_price=64000.0,
        allocation_decision="FALLBACK_NOMINAL_STRATEGY",
        allocation_multiplier=1.0,
        dry_powder_delta=0.0,
        reference_market_price=64000.0,
        pipeline_operations=create_empty_pipeline_operations(),
        pipeline_attempt_count=0,
        suspension_reason=suspension_reason,
    )
