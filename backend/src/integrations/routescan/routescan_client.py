from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx
from web3 import Web3

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

ROUTESCAN_NO_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-store",
    "Pragma": "no-cache",
}
ROUTESCAN_LATEST_TRANSACTION_WINDOW_SIZE: int = 5


class RoutescanClient:
    def __init__(self, wallet_address: str) -> None:
        self._wallet_address: str = wallet_address.lower()
        self._wallet_checksum_address: str = Web3.to_checksum_address(wallet_address)

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    async def close(self) -> None:
        return None

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

    async def fetch_latest_normal_transaction_hash(self) -> str:
        return await self._fetch_latest_transaction_hash(
            account_action=RoutescanAccountAction.NORMAL_TRANSACTION_LIST,
        )

    async def fetch_latest_internal_transaction_hash(self) -> str:
        return await self._fetch_latest_transaction_hash(
            account_action=RoutescanAccountAction.INTERNAL_TRANSACTION_LIST,
        )

    async def fetch_latest_token_transaction_hash(self) -> str:
        return await self._fetch_latest_transaction_hash(
            account_action=RoutescanAccountAction.TOKEN_TRANSACTION_LIST,
        )

    async def _fetch_latest_transaction_hash(self, account_action: RoutescanAccountAction) -> str:
        request_parameters = {
            "module": "account",
            "action": account_action.value,
            "address": self._wallet_checksum_address,
            "startblock": 0,
            "endblock": 99_999_999,
            "page": 1,
            "offset": ROUTESCAN_LATEST_TRANSACTION_WINDOW_SIZE,
            "sort": "desc",
            "apikey": settings.ROUTESCAN_API_KEY,
        }
        response_payload = await self._request_json(request_parameters=request_parameters)
        raw_result = response_payload.get("result")

        if not isinstance(raw_result, list) or len(raw_result) == 0:
            return ""

        latest_record = max(
            raw_result,
            key=lambda raw_record: int(raw_record.get("blockNumber", "0")),
        )
        if not isinstance(latest_record, dict):
            return ""

        transaction_hash = latest_record.get("hash")
        if not isinstance(transaction_hash, str):
            return ""

        return transaction_hash.lower()

    async def _fetch_paginated_raw_records(self, account_action: RoutescanAccountAction) -> list[dict]:
        collected_records: list[dict] = []
        current_page_number: int = 1

        async with httpx.AsyncClient(
                timeout=ROUTESCAN_HTTP_TIMEOUT_SECONDS,
                headers=ROUTESCAN_NO_CACHE_HEADERS,
        ) as http_client:
            while True:
                request_parameters = self._cache_busting_parameters({
                    "module": "account",
                    "action": account_action.value,
                    "address": self._wallet_checksum_address,
                    "startblock": 0,
                    "endblock": 99_999_999,
                    "page": current_page_number,
                    "offset": ROUTESCAN_PAGE_SIZE,
                    "sort": "asc",
                    "apikey": settings.ROUTESCAN_API_KEY,
                })

                response = await http_client.get(
                    ROUTESCAN_AVALANCHE_ETHERSCAN_API_URL,
                    params=request_parameters,
                )
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

    async def _request_json(self, request_parameters: dict[str, object]) -> dict[str, object]:
        async with httpx.AsyncClient(
                timeout=ROUTESCAN_HTTP_TIMEOUT_SECONDS,
                headers=ROUTESCAN_NO_CACHE_HEADERS,
        ) as http_client:
            response = await http_client.get(
                ROUTESCAN_AVALANCHE_ETHERSCAN_API_URL,
                params=self._cache_busting_parameters(request_parameters),
            )
            response.raise_for_status()
            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise RuntimeError("Routescan API returned a non-object JSON payload")
            return response_payload

    @staticmethod
    def _cache_busting_parameters(request_parameters: dict[str, object]) -> dict[str, object]:
        return {
            **request_parameters,
            "_": str(time.time_ns()),
        }
