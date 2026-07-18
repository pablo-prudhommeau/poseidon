from __future__ import annotations

from typing import Optional

import httpx

from src.integrations.frankfurter.frankfurter_constants import (
    FRANKFURTER_HISTORICAL_EURO_TO_USD_URL_TEMPLATE,
    FRANKFURTER_HTTP_TIMEOUT_SECONDS,
    FRANKFURTER_LATEST_USD_TO_EURO_URL,
)
from src.integrations.frankfurter.frankfurter_structures import FrankfurterExchangeRateResponse
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class FrankfurterClient:
    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def fetch_euro_to_usd_rate_for_date(self, exchange_rate_date: str) -> float:
        request_url = FRANKFURTER_HISTORICAL_EURO_TO_USD_URL_TEMPLATE.format(
            exchange_rate_date=exchange_rate_date,
        )
        try:
            http_client = await self._get_http_client()
            response = await http_client.get(request_url)
            response.raise_for_status()
            response_payload = FrankfurterExchangeRateResponse.model_validate(response.json())
            if response_payload.rates.USD is None:
                raise RuntimeError(f"Frankfurter response missing USD rate for date {exchange_rate_date}")
            exchange_rate = response_payload.rates.USD
            logger.debug(
                "[FRANKFURTER][FX] EUR/USD rate resolved date=%s rate=%0.6f",
                exchange_rate_date,
                exchange_rate,
            )
            return exchange_rate
        except Exception as exception:
            logger.exception(
                "[FRANKFURTER][FX] EUR/USD lookup failed for date %s: %s",
                exchange_rate_date,
                exception,
            )
            raise

    async def fetch_usd_to_euro_latest_rate(self) -> float:
        try:
            http_client = await self._get_http_client()
            response = await http_client.get(FRANKFURTER_LATEST_USD_TO_EURO_URL)
            response.raise_for_status()
            response_payload = FrankfurterExchangeRateResponse.model_validate(response.json())
            if response_payload.rates.EUR is None:
                raise RuntimeError("Frankfurter response missing EUR rate")
            exchange_rate = response_payload.rates.EUR
            logger.debug(
                "[FRANKFURTER][FX] USD/EUR latest rate resolved rate=%0.6f",
                exchange_rate,
            )
            return exchange_rate
        except Exception as exception:
            logger.exception(
                "[FRANKFURTER][FX] USD/EUR latest lookup failed: %s",
                exception,
            )
            raise

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=FRANKFURTER_HTTP_TIMEOUT_SECONDS)
        return self._http_client
