from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from src.configuration.config import settings
from src.integrations.routescan.routescan_constants import (
    ROUTESCAN_AVALANCHE_ETHERSCAN_API_URL,
    ROUTESCAN_HTTP_TIMEOUT_SECONDS,
    ROUTESCAN_PAGE_DELAY_SECONDS,
    ROUTESCAN_PAGE_SIZE,
)
from src.integrations.routescan.routescan_structures import (
    RoutescanAccountAction,
    RoutescanInternalTransactionRecord,
    RoutescanNormalTransactionRecord,
    RoutescanTokenTransactionRecord,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class RoutescanClient:
    def __init__(self, wallet_address: str) -> None:
        self._wallet_address: str = wallet_address.lower()
        self._http_client: Optional[httpx.AsyncClient] = None

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def fetch_all_normal_transactions(self) -> list[RoutescanNormalTransactionRecord]:
        raw_records = await self._fetch_paginated_raw_records(
            account_action=RoutescanAccountAction.NORMAL_TRANSACTION_LIST,
        )
        return [RoutescanNormalTransactionRecord.model_validate(raw_record) for raw_record in raw_records]

    async def fetch_all_internal_transactions(self) -> list[RoutescanInternalTransactionRecord]:
        raw_records = await self._fetch_paginated_raw_records(
            account_action=RoutescanAccountAction.INTERNAL_TRANSACTION_LIST,
        )
        return [RoutescanInternalTransactionRecord.model_validate(raw_record) for raw_record in raw_records]

    async def fetch_all_token_transactions(self) -> list[RoutescanTokenTransactionRecord]:
        raw_records = await self._fetch_paginated_raw_records(
            account_action=RoutescanAccountAction.TOKEN_TRANSACTION_LIST,
        )
        return [RoutescanTokenTransactionRecord.model_validate(raw_record) for raw_record in raw_records]

    async def _fetch_paginated_raw_records(self, account_action: RoutescanAccountAction) -> list[dict]:
        collected_records: list[dict] = []
        current_page_number: int = 1

        while True:
            request_parameters = {
                "module": "account",
                "action": account_action.value,
                "address": self._wallet_address,
                "startblock": 0,
                "endblock": 99_999_999,
                "page": current_page_number,
                "offset": ROUTESCAN_PAGE_SIZE,
                "sort": "asc",
                "apikey": settings.ROUTESCAN_API_KEY,
            }

            http_client = await self._get_http_client()
            response = await http_client.get(ROUTESCAN_AVALANCHE_ETHERSCAN_API_URL, params=request_parameters)
            response.raise_for_status()
            response_payload = response.json()
            raw_result = response_payload.get("result")

            if not isinstance(raw_result, list) or len(raw_result) == 0:
                break

            for raw_record in raw_result:
                if isinstance(raw_record, dict):
                    collected_records.append(raw_record)

            if len(raw_result) < ROUTESCAN_PAGE_SIZE:
                break

            current_page_number += 1
            await asyncio.sleep(ROUTESCAN_PAGE_DELAY_SECONDS)

        logger.debug(
            "[ROUTESCAN][CLIENT] Paginated fetch completed action=%s record_count=%d",
            account_action.value,
            len(collected_records),
        )
        return collected_records

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=ROUTESCAN_HTTP_TIMEOUT_SECONDS)
        return self._http_client
