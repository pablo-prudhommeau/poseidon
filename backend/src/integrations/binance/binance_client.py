from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List

import httpx

from src.core.utils.date_utils import convert_epoch_to_local_datetime
from src.integrations.binance.binance_structures import (
    ExponentialMovingAverageAndPrice,
    CandlestickData
)
from src.logging.logger import get_logger

logger = get_logger(__name__)


async def fetch_exponential_moving_average_and_price(
        symbol: str,
        interval: str,
        limit: int
) -> ExponentialMovingAverageAndPrice:
    url = "https://api.binance.com/api/v3/klines"
    query_parameters = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    logger.info("[BINANCE][CLIENT][EMA] Fetching exponential moving average and price for symbol: %s", symbol)
    logger.debug("[BINANCE][CLIENT][EMA] Request parameters: %s", query_parameters)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=query_parameters, timeout=10.0)
            response.raise_for_status()
            payload = response.json()
    except Exception as exception:
        logger.exception("[BINANCE][CLIENT][EMA] Failed to retrieve data for %s: %s", symbol, exception)
        raise RuntimeError(f"Failed to fetch candlestick data for {symbol}") from exception

    if not payload:
        logger.error("[BINANCE][CLIENT][EMA] Empty payload received for symbol: %s", symbol)
        raise RuntimeError(f"Empty candlestick payload received for {symbol}")

    closing_prices = [float(candlestick[4]) for candlestick in payload]
    exponential_moving_average_value = closing_prices[0]
    smoothing_multiplier = 2.0 / (50.0 + 1.0)

    for current_closing_price in closing_prices[1:]:
        exponential_moving_average_value = (
                (current_closing_price - exponential_moving_average_value) * smoothing_multiplier
                + exponential_moving_average_value
        )

    logger.info(
        "[BINANCE][CLIENT][EMA] Successfully calculated exponential moving average for %s: %f",
        symbol,
        exponential_moving_average_value
    )

    return ExponentialMovingAverageAndPrice(
        exponential_moving_average=exponential_moving_average_value,
        latest_closing_price=closing_prices[-1]
    )


async def fetch_bulk_historical_candlesticks(
        symbol: str,
        start_time: datetime,
        end_time: datetime
) -> List[CandlestickData]:
    url = "https://api.binance.com/api/v3/klines"
    all_candlesticks: List[CandlestickData] = []
    current_start_time_milliseconds = int(start_time.timestamp() * 1000)
    end_time_milliseconds = int(end_time.timestamp() * 1000)

    logger.info(
        "[BINANCE][CLIENT][BULK_HISTORY] Starting bulk history fetch for %s from %s to %s",
        symbol,
        start_time.isoformat(),
        end_time.isoformat()
    )

    try:
        async with httpx.AsyncClient() as client:
            while current_start_time_milliseconds < end_time_milliseconds:
                query_parameters = {
                    "symbol": symbol,
                    "interval": "1h",
                    "startTime": current_start_time_milliseconds,
                    "endTime": end_time_milliseconds,
                    "limit": 1000
                }

                logger.debug(
                    "[BINANCE][CLIENT][BULK_HISTORY] Fetching chunk for %s starting at %s",
                    symbol,
                    convert_epoch_to_local_datetime(current_start_time_milliseconds).astimezone(tz=start_time.tzinfo).isoformat()
                )

                response = await client.get(url, params=query_parameters, timeout=15.0)
                response.raise_for_status()
                payload = response.json()

                if not payload:
                    logger.debug("[BINANCE][CLIENT][BULK_HISTORY] No more data returned by the API for %s.", symbol)
                    break

                for candlestick in payload:
                    candlestick_data = CandlestickData(
                        closing_timestamp_milliseconds=candlestick[0],
                        closing_price=float(candlestick[4])
                    )
                    all_candlesticks.append(candlestick_data)

                current_start_time_milliseconds = int(payload[-1][6]) + 1
                await asyncio.sleep(0.1)

        logger.info(
            "[BINANCE][CLIENT][BULK_HISTORY] Successfully fetched %d candlesticks for %s.",
            len(all_candlesticks),
            symbol
        )
        return all_candlesticks

    except Exception as exception:
        logger.error(
            "[BINANCE][CLIENT][BULK_HISTORY] Bulk historical fetch failed for %s: %s",
            symbol,
            exception
        )
        raise RuntimeError(f"Failed to fetch bulk historical data for {symbol}") from exception
