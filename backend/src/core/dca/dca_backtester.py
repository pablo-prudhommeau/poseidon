from __future__ import annotations

from datetime import datetime
from typing import List, Dict

from src.core.dca.dca_allocation_engine import DcaAllocationEngine
from src.core.structures.structures import DcaBacktestSeriesPoint, DcaBacktestMetadata, DcaBacktestPayload
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
            executions_count: int,
            pru_elasticity_factor: float
    ) -> DcaBacktestPayload:

        logger.info(
            "[DCA][BACKTESTER] Initiating dynamic sizing simulation for symbol %s with %d executions.",
            symbol,
            executions_count
        )

        if executions_count <= 0 or total_budget <= 0.0:
            logger.error("[DCA][BACKTESTER] Invalid parameters: budget or executions must be strictly positive.")
            raise ValueError("Total budget and executions count must be strictly positive.")

        historical_candlesticks: List[CandlestickData] = await fetch_bulk_historical_candlesticks(
            symbol=symbol,
            start_time=start_date,
            end_time=end_date
        )

        if not historical_candlesticks:
            logger.error("[DCA][BACKTESTER] Failed to fetch historical market data from Binance for %s.", symbol)
            raise RuntimeError(f"Cannot perform backtest: No historical data available for {symbol}.")

        exponential_moving_average_map: Dict[int, float] = {}
        price_map: Dict[int, float] = {}

        current_exponential_moving_average = historical_candlesticks[0].closing_price
        exponential_moving_average_span_hours = 50 * 24
        smoothing_factor = 2.0 / (exponential_moving_average_span_hours + 1.0)

        for candlestick in historical_candlesticks:
            current_exponential_moving_average = (
                    (candlestick.closing_price - current_exponential_moving_average) * smoothing_factor
                    + current_exponential_moving_average
            )
            exponential_moving_average_map[candlestick.closing_timestamp_milliseconds] = current_exponential_moving_average
            price_map[candlestick.closing_timestamp_milliseconds] = candlestick.closing_price

        target_start_timestamp_milliseconds = int(start_date.timestamp() * 1000)

        valid_timestamps = [
            candlestick.closing_timestamp_milliseconds
            for candlestick in historical_candlesticks
            if candlestick.closing_timestamp_milliseconds >= target_start_timestamp_milliseconds
        ]

        if not valid_timestamps:
            logger.error("[DCA][BACKTESTER] No valid timestamps found within the requested execution window.")
            raise RuntimeError("Simulation window does not contain any valid market data timestamps.")

        end_timestamp_milliseconds = int(end_date.timestamp() * 1000)
        interval_milliseconds = (end_timestamp_milliseconds - target_start_timestamp_milliseconds) / executions_count
        theoretical_execution_dates = [
            target_start_timestamp_milliseconds + int(iteration * interval_milliseconds)
            for iteration in range(executions_count)
        ]

        budget_per_execution = total_budget / executions_count

        dumb_dca_results: List[DcaBacktestSeriesPoint] = []
        smart_dca_results: List[DcaBacktestSeriesPoint] = []

        dumb_cumulative_spent = 0.0
        dumb_crypto_accumulated = 0.0

        smart_cumulative_spent = 0.0
        smart_crypto_accumulated = 0.0
        smart_dry_powder_reserves = 0.0
        smart_average_unit_price = 0.0
        total_overheat_retentions = 0

        for iteration, expected_timestamp in enumerate(theoretical_execution_dates):
            execution_timestamp = DcaBacktester._find_closest_timestamp(valid_timestamps, expected_timestamp)

            execution_local_iso_date = convert_epoch_to_local_datetime(execution_timestamp).isoformat()

            current_market_price = price_map[execution_timestamp]
            current_macro_exponential_moving_average = exponential_moving_average_map[execution_timestamp]

            dumb_cumulative_spent += budget_per_execution
            if current_market_price > 0.0:
                dumb_crypto_accumulated += budget_per_execution / current_market_price

            dumb_average_unit_price = (
                dumb_cumulative_spent / dumb_crypto_accumulated
                if dumb_crypto_accumulated > 0.0
                else 0.0
            )

            dumb_dca_results.append(
                DcaBacktestSeriesPoint(
                    timestamp_iso=execution_local_iso_date,
                    execution_price=current_market_price,
                    average_purchase_price=dumb_average_unit_price,
                    cumulative_spent=dumb_cumulative_spent,
                    dry_powder_remaining=0.0
                )
            )

            is_last_execution = (iteration == executions_count - 1)

            allocation_decision = DcaAllocationEngine.calculate_allocation(
                nominal_tranche=budget_per_execution,
                current_dry_powder=smart_dry_powder_reserves,
                current_price=current_market_price,
                current_macro_ema=current_macro_exponential_moving_average,
                current_pru=smart_average_unit_price,
                is_last_execution=is_last_execution,
                pru_elasticity_factor=pru_elasticity_factor
            )

            smart_spend_amount = allocation_decision.spend_amount
            smart_dry_powder_reserves += allocation_decision.dry_powder_delta

            if "RETENTION" in allocation_decision.action_description:
                total_overheat_retentions += 1

            smart_cumulative_spent += smart_spend_amount
            if current_market_price > 0.0:
                smart_crypto_accumulated += smart_spend_amount / current_market_price

            smart_average_unit_price = (
                smart_cumulative_spent / smart_crypto_accumulated
                if smart_crypto_accumulated > 0.0
                else 0.0
            )

            logger.debug(
                "[DCA][BACKTESTER] [%s] Price: $%.2f | EMA: $%.2f | PRU: $%.2f | Action: %s | Deployed: $%.2f | Vault: $%.2f",
                execution_local_iso_date,
                current_market_price,
                current_macro_exponential_moving_average,
                smart_average_unit_price,
                allocation_decision.action_description,
                smart_spend_amount,
                smart_dry_powder_reserves
            )

            smart_dca_results.append(
                DcaBacktestSeriesPoint(
                    timestamp_iso=execution_local_iso_date,
                    execution_price=current_market_price,
                    average_purchase_price=smart_average_unit_price,
                    cumulative_spent=smart_cumulative_spent,
                    dry_powder_remaining=smart_dry_powder_reserves
                )
            )

        final_dumb_average_unit_price = dumb_dca_results[-1].average_purchase_price if dumb_dca_results else 0.0
        final_smart_average_unit_price = smart_dca_results[-1].average_purchase_price if smart_dca_results else 0.0

        logger.info(
            "[DCA][BACKTESTER] Simulation completed for %s. Dumb PRU: $%.2f | Smart PRU: $%.2f | Retentions: %d",
            symbol,
            final_dumb_average_unit_price,
            final_smart_average_unit_price,
            total_overheat_retentions
        )

        return DcaBacktestPayload(
            metadata=DcaBacktestMetadata(
                symbol=symbol,
                total_budget=total_budget,
                executions=executions_count,
                final_dumb_average_unit_price=final_dumb_average_unit_price,
                final_smart_average_unit_price=final_smart_average_unit_price,
                total_overheat_retentions=total_overheat_retentions
            ),
            dumb_dca_series=dumb_dca_results,
            smart_dca_series=smart_dca_results
        )

    @staticmethod
    def _find_closest_timestamp(timestamps: List[int], target_timestamp: int) -> int:
        return min(timestamps, key=lambda current_timestamp: abs(current_timestamp - target_timestamp))
