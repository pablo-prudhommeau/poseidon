from __future__ import annotations

from datetime import datetime

from src.core.dca.dca_allocation_engine import DcaAllocationEngine
from src.core.structures.structures import (
    DcaBacktestSeriesPoint,
    DcaBacktestMetadata,
    DcaBacktestPayload
)
from src.core.utils.date_utils import convert_epoch_to_local_datetime
from src.integrations.binance.binance_client import fetch_bulk_historical_candlesticks
from src.integrations.binance.binance_structures import CandlestickData
from src.logging.logger import get_logger

logger = get_logger(__name__)


class DcaBacktester:

    @staticmethod
    async def generate_comparative_snapshot(
            symbol: str,
            start_date: datetime,
            end_date: datetime,
            total_budget: float,
            total_execution_cycles: int,
            price_elasticity_aggressiveness: float
    ) -> DcaBacktestPayload:
        logger.info(
            "[DCA][BACKTESTER][START] Initiating comparative simulation for %s with %d cycles",
            symbol,
            total_execution_cycles
        )

        if total_execution_cycles <= 0 or total_budget <= 0.0:
            logger.error("[DCA][BACKTESTER][VALIDATION] Total budget and execution cycles must be strictly positive")
            raise ValueError("Simulation parameters must be strictly positive")

        historical_candlesticks: list[CandlestickData] = await fetch_bulk_historical_candlesticks(
            symbol=symbol,
            start_time=start_date,
            end_time=end_date
        )

        if not historical_candlesticks:
            logger.error("[DCA][BACKTESTER][DATA] Failed to retrieve historical market data for %s", symbol)
            raise RuntimeError(f"Backtest aborted: No market data available for {symbol}")

        ema_calculations_map: dict[int, float] = {}
        market_price_map: dict[int, float] = {}

        current_exponential_moving_average = historical_candlesticks[0].closing_price
        ema_window_hours = 1200
        smoothing_factor = 2.0 / (ema_window_hours + 1.0)

        for candlestick in historical_candlesticks:
            current_exponential_moving_average = (
                    (candlestick.closing_price - current_exponential_moving_average) * smoothing_factor
                    + current_exponential_moving_average
            )
            ema_calculations_map[candlestick.closing_timestamp_milliseconds] = current_exponential_moving_average
            market_price_map[candlestick.closing_timestamp_milliseconds] = candlestick.closing_price

        start_timestamp_milliseconds = int(start_date.timestamp() * 1000)
        valid_market_timestamps = [
            candlestick.closing_timestamp_milliseconds
            for candlestick in historical_candlesticks
            if candlestick.closing_timestamp_milliseconds >= start_timestamp_milliseconds
        ]

        if not valid_market_timestamps:
            logger.error("[DCA][BACKTESTER][DATA] Simulation window contains no valid market timestamps")
            raise RuntimeError("Simulation window is outside of available market data range")

        end_timestamp_milliseconds = int(end_date.timestamp() * 1000)
        cycle_interval_milliseconds = (end_timestamp_milliseconds - start_timestamp_milliseconds) / total_execution_cycles
        scheduled_execution_timestamps = [
            start_timestamp_milliseconds + int(index * cycle_interval_milliseconds)
            for index in range(total_execution_cycles)
        ]

        budget_per_execution_cycle = total_budget / total_execution_cycles

        standard_dca_series: list[DcaBacktestSeriesPoint] = []
        dynamic_dca_series: list[DcaBacktestSeriesPoint] = []

        standard_cumulative_spent = 0.0
        standard_accumulated_asset_units = 0.0

        dynamic_cumulative_spent = 0.0
        dynamic_accumulated_asset_units = 0.0
        dynamic_dry_powder_reserve = 0.0
        dynamic_average_purchase_price = 0.0
        total_market_overheat_preventions = 0

        for cycle_index, target_timestamp in enumerate(scheduled_execution_timestamps):
            actual_execution_timestamp = DcaBacktester._resolve_closest_market_timestamp(
                valid_market_timestamps,
                target_timestamp
            )

            execution_date_iso = convert_epoch_to_local_datetime(actual_execution_timestamp).isoformat()
            current_market_price = market_price_map[actual_execution_timestamp]
            current_macro_ema = ema_calculations_map[actual_execution_timestamp]

            standard_cumulative_spent += budget_per_execution_cycle
            if current_market_price > 0.0:
                standard_accumulated_asset_units += budget_per_execution_cycle / current_market_price

            standard_average_purchase_price = (
                standard_cumulative_spent / standard_accumulated_asset_units
                if standard_accumulated_asset_units > 0.0
                else 0.0
            )

            standard_dca_series.append(
                DcaBacktestSeriesPoint(
                    timestamp_iso=execution_date_iso,
                    execution_price=current_market_price,
                    average_purchase_price=standard_average_purchase_price,
                    cumulative_spent=standard_cumulative_spent,
                    dry_powder_remaining=0.0
                )
            )

            is_final_cycle = (cycle_index == total_execution_cycles - 1)

            allocation_verdict = DcaAllocationEngine.calculate_dynamic_allocation(
                nominal_investment_amount=budget_per_execution_cycle,
                current_dry_powder_reserve=dynamic_dry_powder_reserve,
                current_market_price=current_market_price,
                current_macro_ema=current_macro_ema,
                current_average_purchase_price=dynamic_average_purchase_price,
                is_last_execution_cycle=is_final_cycle,
                price_elasticity_aggressiveness=price_elasticity_aggressiveness
            )

            cycle_spend_amount = allocation_verdict.spend_amount
            dynamic_dry_powder_reserve += allocation_verdict.dry_powder_delta

            if "RETENTION" in allocation_verdict.action_description:
                total_market_overheat_preventions += 1

            dynamic_cumulative_spent += cycle_spend_amount
            if current_market_price > 0.0:
                dynamic_accumulated_asset_units += cycle_spend_amount / current_market_price

            dynamic_average_purchase_price = (
                dynamic_cumulative_spent / dynamic_accumulated_asset_units
                if dynamic_accumulated_asset_units > 0.0
                else 0.0
            )

            logger.debug(
                "[DCA][BACKTESTER][STEP] [%s] Price: %s | Action: %s | Spent: %s | PRU: %s",
                execution_date_iso,
                current_market_price,
                allocation_verdict.action_description,
                cycle_spend_amount,
                dynamic_average_purchase_price
            )

            dynamic_dca_series.append(
                DcaBacktestSeriesPoint(
                    timestamp_iso=execution_date_iso,
                    execution_price=current_market_price,
                    average_purchase_price=dynamic_average_purchase_price,
                    cumulative_spent=dynamic_cumulative_spent,
                    dry_powder_remaining=dynamic_dry_powder_reserve
                )
            )

        final_standard_pru = standard_dca_series[-1].average_purchase_price if standard_dca_series else 0.0
        final_dynamic_pru = dynamic_dca_series[-1].average_purchase_price if dynamic_dca_series else 0.0

        logger.info(
            "[DCA][BACKTESTER][FINISH] Completed for %s. Standard PRU: %s | Dynamic PRU: %s",
            symbol,
            final_standard_pru,
            final_dynamic_pru
        )

        return DcaBacktestPayload(
            metadata=DcaBacktestMetadata(
                source_asset_symbol=symbol,
                total_allocated_budget=total_budget,
                total_planned_executions=total_execution_cycles,
                final_dumb_average_unit_price=final_standard_pru,
                final_smart_average_unit_price=final_dynamic_pru,
                total_overheat_retentions=total_market_overheat_preventions
            ),
            dumb_dca_series=standard_dca_series,
            smart_dca_series=dynamic_dca_series
        )

    @staticmethod
    def _resolve_closest_market_timestamp(market_timestamps: list[int], target_timestamp: int) -> int:
        return min(market_timestamps, key=lambda current_timestamp: abs(current_timestamp - target_timestamp))
