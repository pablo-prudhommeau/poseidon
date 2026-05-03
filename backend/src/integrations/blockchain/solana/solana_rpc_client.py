from __future__ import annotations

import base64
import struct
import time
from typing import Optional

import requests

from src.integrations.blockchain.blockchain_rpc_registry import FREE_RPC_ENDPOINTS, PREMIUM_RPC_SETTING_BY_CHAIN
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_KNOWN_STABLECOIN_MINTS,
    SOLANA_SPL_TOKEN_BALANCE_OFFSET,
    SOLANA_WRAPPED_SOL_MINT,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SOLANA_RPC_TIMEOUT_SECONDS = 8
SOLANA_SOL_USD_CACHE_TTL_SECONDS = 30

SOLANA_SOL_USDC_REFERENCE_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"

_cached_sol_usd_price: Optional[float] = None
_cached_sol_usd_timestamp: float = 0.0

_spl_decimals_cache: dict[str, int] = {}


def get_solana_rpc_url() -> str:
    from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
    return resolve_rpc_url_for_chain("solana")


def _build_solana_rpc_endpoint_list() -> list[str]:
    from src.configuration.config import settings

    endpoints: list[str] = []

    premium_setting_name = PREMIUM_RPC_SETTING_BY_CHAIN.get("solana", "")
    if premium_setting_name:
        premium_url = getattr(settings, premium_setting_name, "")
        if premium_url:
            endpoints.append(premium_url)

    free_endpoints = FREE_RPC_ENDPOINTS.get("solana", [])
    endpoints.extend(free_endpoints)

    return endpoints


def _rpc_post(rpc_url: str, payload: dict) -> Optional[dict]:
    try:
        response = requests.post(
            rpc_url,
            json=payload,
            timeout=SOLANA_RPC_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 429:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] Rate-limited (HTTP 429) at %s", rpc_url)
            return None
        if response.status_code != 200:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] HTTP %d at %s", response.status_code, rpc_url)
            return None
        return response.json()
    except requests.exceptions.Timeout:
        logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] Timeout at %s", rpc_url)
        return None
    except requests.exceptions.RequestException as e:
        logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] Network error at %s: %s", rpc_url, str(e))
        return None
    except Exception as e:
        logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] Unexpected error at %s: %s", rpc_url, str(e))
        return None


def rpc_get_account_info(rpc_url: str, account_address: str) -> Optional[dict]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [account_address, {"encoding": "base64"}],
    }

    response_json = _rpc_post(rpc_url, payload)
    if response_json is not None:
        result = response_json.get("result")
        if result is not None and result.get("value") is not None:
            return result["value"]

    for fallback_url in _build_solana_rpc_endpoint_list():
        if fallback_url == rpc_url:
            continue
        logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] Fallback getAccountInfo for %s via %s", account_address[:12], fallback_url)
        response_json = _rpc_post(fallback_url, payload)
        if response_json is not None:
            result = response_json.get("result")
            if result is not None and result.get("value") is not None:
                return result["value"]

    logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] getAccountInfo exhausted all endpoints for %s", account_address[:12])
    return None


def rpc_get_multiple_accounts(rpc_url: str, account_addresses: list[str]) -> list[Optional[dict]]:
    if not account_addresses:
        return []

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getMultipleAccounts",
        "params": [account_addresses, {"encoding": "base64"}],
    }

    response_json = _rpc_post(rpc_url, payload)
    if response_json is not None:
        result = response_json.get("result")
        if result is not None and result.get("value") is not None:
            return result["value"]

    for fallback_url in _build_solana_rpc_endpoint_list():
        if fallback_url == rpc_url:
            continue
        logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] Fallback getMultipleAccounts for %d accounts via %s", len(account_addresses), fallback_url)
        response_json = _rpc_post(fallback_url, payload)
        if response_json is not None:
            result = response_json.get("result")
            if result is not None and result.get("value") is not None:
                return result["value"]

    logger.debug("[BLOCKCHAIN][PRICE][SOL][RPC] getMultipleAccounts exhausted all endpoints for %d accounts", len(account_addresses))
    return [None] * len(account_addresses)


def decode_account_data(account_info: dict) -> Optional[bytes]:
    data_field = account_info.get("data")
    if data_field is None:
        return None
    if isinstance(data_field, list) and len(data_field) >= 2 and data_field[1] == "base64":
        return base64.b64decode(data_field[0])
    return None


def extract_owner_program(account_info: dict) -> str:
    return account_info.get("owner", "")


def fetch_spl_token_balance(rpc_url: str, vault_address: str) -> Optional[int]:
    account_info = rpc_get_account_info(rpc_url, vault_address)
    if account_info is None:
        return None
    account_data = decode_account_data(account_info)
    if account_data is None or len(account_data) < 72:
        return None
    balance = struct.unpack_from("<Q", account_data, SOLANA_SPL_TOKEN_BALANCE_OFFSET)[0]
    return balance


def get_spl_token_decimals(rpc_url: str, mint_address: str) -> Optional[int]:
    cached_value = _spl_decimals_cache.get(mint_address)
    if cached_value is not None:
        return cached_value
    account_info = rpc_get_account_info(rpc_url, mint_address)
    if account_info is not None:
        account_data = decode_account_data(account_info)
        if account_data is not None and len(account_data) >= 45:
            fetched_decimals = struct.unpack_from("<B", account_data, 44)[0]
            _spl_decimals_cache[mint_address] = fetched_decimals
            return fetched_decimals
    return None


def resolve_sol_usd_price(rpc_url: str) -> Optional[float]:
    global _cached_sol_usd_price, _cached_sol_usd_timestamp

    now = time.monotonic()
    if _cached_sol_usd_price is not None and (now - _cached_sol_usd_timestamp) < SOLANA_SOL_USD_CACHE_TTL_SECONDS:
        return _cached_sol_usd_price

    from src.integrations.blockchain.solana.solana_structures import SOLANA_DEX_PROGRAM_IDS
    from src.integrations.blockchain.solana.dex_parsers.raydium_pool_parser import RaydiumPoolParser

    account_info = rpc_get_account_info(rpc_url, SOLANA_SOL_USDC_REFERENCE_POOL)
    if account_info is None:
        logger.warning("[BLOCKCHAIN][PRICE][SOL][REFERENCE] Failed to fetch SOL/USDC reference pool from all endpoints")
        return _cached_sol_usd_price

    account_data = decode_account_data(account_info)
    if account_data is None:
        return _cached_sol_usd_price

    owner_program = extract_owner_program(account_info)
    raydium_parser = RaydiumPoolParser()

    price_result = None
    if owner_program in {SOLANA_DEX_PROGRAM_IDS["raydium_amm_v4"], SOLANA_DEX_PROGRAM_IDS["raydium_clmm"]}:
        price_result = raydium_parser.parse_pool_price(rpc_url, account_data, SOLANA_WRAPPED_SOL_MINT, owner_program)

    if price_result is None:
        logger.warning("[BLOCKCHAIN][PRICE][SOL][REFERENCE] Cannot parse SOL/USDC reference pool")
        return _cached_sol_usd_price

    sol_usd_price = price_result[0]
    if sol_usd_price <= 0:
        return _cached_sol_usd_price

    _cached_sol_usd_price = sol_usd_price
    _cached_sol_usd_timestamp = now
    logger.debug("[BLOCKCHAIN][PRICE][SOL][REFERENCE] SOL/USD = %.4f", sol_usd_price)
    return sol_usd_price


def convert_price_to_usd(
        rpc_url: str,
        price_in_quote: float,
        quote_token_mint: str,
) -> Optional[float]:
    if quote_token_mint in SOLANA_KNOWN_STABLECOIN_MINTS:
        return price_in_quote

    if quote_token_mint == SOLANA_WRAPPED_SOL_MINT:
        sol_usd = resolve_sol_usd_price(rpc_url)
        if sol_usd is None or sol_usd <= 0:
            return None
        return price_in_quote * sol_usd

    logger.debug("[BLOCKCHAIN][PRICE][SOL] Unknown quote mint %s, cannot convert to USD", quote_token_mint[:12])
    return None
