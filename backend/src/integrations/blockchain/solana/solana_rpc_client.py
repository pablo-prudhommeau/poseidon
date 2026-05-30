from __future__ import annotations

import base64
import struct
import time
from datetime import datetime
from typing import Optional

import requests

from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import convert_epoch_to_local_datetime
from src.integrations.blockchain.blockchain_rpc_registry import (
    invalidate_rpc_cache_for_chain,
    list_fallback_rpc_urls_for_chain,
)
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_KNOWN_STABLECOIN_MINTS,
    SOLANA_SPL_TOKEN_BALANCE_OFFSET,
    SOLANA_SPL_TOKEN_ACCOUNT_DATA_LENGTH,
    SOLANA_SPL_TOKEN_PROGRAM_ID,
    SOLANA_TOKEN_2022_PROGRAM_ID,
    SOLANA_WRAPPED_SOL_MINT,
    SolanaWalletTokenAccountSnapshot,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SOLANA_RPC_TIMEOUT_SECONDS = 8
SOLANA_SOL_USD_CACHE_TTL_SECONDS = 30
SOLANA_NATIVE_BALANCE_POLL_INTERVAL_SECONDS = 2.0
SOLANA_NATIVE_BALANCE_POLL_TIMEOUT_SECONDS = 30.0

SOLANA_SOL_USDC_REFERENCE_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"

_cached_sol_usd_price: Optional[float] = None
_cached_sol_usd_timestamp: float = 0.0

_spl_decimals_cache: dict[str, int] = {}


def get_solana_rpc_url() -> str:
    from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
    return resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)


def _rpc_post(rpc_url: str, payload: dict) -> Optional[dict]:
    rpc_method = str(payload.get("method", "unknown"))
    try:
        response = requests.post(
            rpc_url,
            json=payload,
            timeout=SOLANA_RPC_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 429:
            logger.debug(
                "[BLOCKCHAIN][SOL][RPC] RPC request rate-limited — rpc_method=%s rpc_url=%s http_status=429",
                rpc_method,
                rpc_url,
            )
            return None
        if response.status_code != 200:
            logger.debug(
                "[BLOCKCHAIN][SOL][RPC] RPC request failed with non-200 status — "
                "rpc_method=%s rpc_url=%s http_status=%d",
                rpc_method,
                rpc_url,
                response.status_code,
            )
            return None
        return response.json()
    except requests.exceptions.Timeout:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] RPC request timeout — rpc_method=%s rpc_url=%s",
            rpc_method,
            rpc_url,
        )
        return None
    except requests.exceptions.RequestException as e:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] RPC network error — rpc_method=%s rpc_url=%s error=%s",
            rpc_method,
            rpc_url,
            str(e),
        )
        return None
    except Exception as e:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] RPC unexpected error — rpc_method=%s rpc_url=%s error=%s",
            rpc_method,
            rpc_url,
            str(e),
        )
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

    for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
        response_json = _rpc_post(fallback_url, payload)
        if response_json is not None:
            result = response_json.get("result")
            if result is not None and result.get("value") is not None:
                logger.debug(
                    "[BLOCKCHAIN][SOL][RPC] getAccountInfo recovered via fallback endpoint — "
                    "account_address_prefix=%s rpc_url=%s",
                    account_address[:12],
                    fallback_url,
                )
                return result["value"]

    logger.warning(
        "[BLOCKCHAIN][SOL][RPC] getAccountInfo failed across all endpoints — "
        "account_address_prefix=%s reason=rpc_endpoints_exhausted",
        account_address[:12],
    )
    invalidate_rpc_cache_for_chain(BlockchainNetwork.SOLANA)
    return None


def rpc_get_multiple_accounts(rpc_url: str, account_addresses: list[str]) -> list[Optional[dict]]:
    if not account_addresses:
        return []

    MAX_ACCOUNTS_PER_REQUEST = 10
    all_results = []

    for i in range(0, len(account_addresses), MAX_ACCOUNTS_PER_REQUEST):
        chunk = account_addresses[i:i + MAX_ACCOUNTS_PER_REQUEST]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getMultipleAccounts",
            "params": [chunk, {"encoding": "base64"}],
        }

        response_json = _rpc_post(rpc_url, payload)
        chunk_result = None

        if response_json is not None:
            result = response_json.get("result")
            if result is not None and result.get("value") is not None:
                chunk_result = result["value"]

        if chunk_result is None:
            for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
                response_json = _rpc_post(fallback_url, payload)
                if response_json is not None:
                    result = response_json.get("result")
                    if result is not None and result.get("value") is not None:
                        chunk_result = result["value"]
                        logger.debug(
                            "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts recovered via fallback endpoint — "
                            "chunk_account_count=%d rpc_url=%s",
                            len(chunk),
                            fallback_url,
                        )
                        break

        if chunk_result is None:
            logger.warning(
                "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts failed across all endpoints — "
                "chunk_account_count=%d reason=rpc_endpoints_exhausted",
                len(chunk),
            )
            invalidate_rpc_cache_for_chain(BlockchainNetwork.SOLANA)
            chunk_result = [None] * len(chunk)

        all_results.extend(chunk_result)

    return all_results


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


def fetch_spl_token_balance_for_wallet_and_mint(
        rpc_url: str,
        wallet_address: str,
        token_mint_address: str,
) -> Optional[int]:
    token_accounts = list_wallet_spl_token_accounts(rpc_url, wallet_address)
    for token_account in token_accounts:
        if token_account.token_mint_address != token_mint_address:
            continue
        return token_account.balance_raw
    return 0


def rpc_get_minimum_balance_for_rent_exemption(rpc_url: str, account_data_length: int) -> Optional[int]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getMinimumBalanceForRentExemption",
        "params": [account_data_length],
    }
    response_json = _rpc_post(rpc_url, payload)
    if response_json is None:
        for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
            response_json = _rpc_post(fallback_url, payload)
            if response_json is not None:
                break
    if response_json is None:
        logger.warning(
            "[BLOCKCHAIN][SOL][RPC] getMinimumBalanceForRentExemption failed across all endpoints — "
            "account_data_length=%d reason=rpc_endpoints_exhausted",
            account_data_length,
        )
        return None
    result_value = response_json.get("result")
    if result_value is None:
        return None
    return int(result_value)


def list_wallet_spl_token_accounts(rpc_url: str, wallet_address: str) -> list[SolanaWalletTokenAccountSnapshot]:
    token_account_entries: list[dict] = []
    supported_program_ids = [SOLANA_SPL_TOKEN_PROGRAM_ID, SOLANA_TOKEN_2022_PROGRAM_ID]
    for supported_program_id in supported_program_ids:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_address,
                {"programId": supported_program_id},
                {"encoding": "jsonParsed"},
            ],
        }
        response_json = _rpc_post(rpc_url, payload)
        if response_json is None:
            for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
                response_json = _rpc_post(fallback_url, payload)
                if response_json is not None:
                    break
        if response_json is None:
            logger.warning(
                "[BLOCKCHAIN][SOL][RPC] getTokenAccountsByOwner failed across all endpoints — "
                "wallet_address=%s owner_program_id=%s reason=rpc_endpoints_exhausted",
                wallet_address,
                supported_program_id,
            )
            continue

        fetched_entries = response_json.get("result", {}).get("value", [])
        if isinstance(fetched_entries, list):
            token_account_entries.extend(fetched_entries)

    if not token_account_entries:
        return []

    deduplicated_entries_by_pubkey: dict[str, dict] = {}
    for token_account_entry in token_account_entries:
        if not isinstance(token_account_entry, dict):
            continue
        token_account_pubkey = str(token_account_entry.get("pubkey", ""))
        if token_account_pubkey:
            deduplicated_entries_by_pubkey[token_account_pubkey] = token_account_entry

    parsed_accounts: list[SolanaWalletTokenAccountSnapshot] = []
    for token_account_entry in deduplicated_entries_by_pubkey.values():
        token_account_address = str(token_account_entry.get("pubkey", ""))
        account_payload = token_account_entry.get("account")
        if not isinstance(account_payload, dict):
            continue
        owner_program_id = str(account_payload.get("owner", ""))
        parsed_data = account_payload.get("data")
        if not isinstance(parsed_data, dict):
            continue
        parsed_info = parsed_data.get("parsed")
        if not isinstance(parsed_info, dict):
            continue
        account_info = parsed_info.get("info")
        if not isinstance(account_info, dict):
            continue
        token_mint_address = str(account_info.get("mint", ""))
        token_amount_payload = account_info.get("tokenAmount")
        if not isinstance(token_amount_payload, dict):
            continue
        balance_text = str(token_amount_payload.get("amount", "0"))
        balance_raw = int(balance_text)
        if not token_account_address or not token_mint_address:
            continue
        parsed_accounts.append(
            SolanaWalletTokenAccountSnapshot(
                token_account_address=token_account_address,
                token_mint_address=token_mint_address,
                balance_raw=balance_raw,
                owner_program_id=owner_program_id,
            )
        )
    return parsed_accounts


def rpc_get_latest_confirmed_transaction_block_time(rpc_url: str, account_address: str) -> Optional[int]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [
            account_address,
            {"limit": 1},
        ],
    }

    response_json = _rpc_post(rpc_url, payload)
    if response_json is not None:
        signature_entries = response_json.get("result")
        if isinstance(signature_entries, list) and signature_entries:
            block_time_value = signature_entries[0].get("blockTime")
            if block_time_value is not None:
                return int(block_time_value)

    for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
        response_json = _rpc_post(fallback_url, payload)
        if response_json is None:
            continue
        signature_entries = response_json.get("result")
        if not isinstance(signature_entries, list) or not signature_entries:
            continue
        block_time_value = signature_entries[0].get("blockTime")
        if block_time_value is None:
            continue
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] getSignaturesForAddress recovered via fallback endpoint — "
            "account_address_prefix=%s rpc_url=%s",
            account_address[:12],
            fallback_url,
        )
        return int(block_time_value)

    logger.debug(
        "[BLOCKCHAIN][SOL][RPC] getSignaturesForAddress returned no confirmed signatures — "
        "account_address_prefix=%s",
        account_address[:12],
    )
    return None


def fetch_token_account_last_activity_datetime(
        rpc_url: str,
        token_account_address: str,
) -> Optional[datetime]:
    latest_transaction_block_time = rpc_get_latest_confirmed_transaction_block_time(rpc_url, token_account_address)
    if latest_transaction_block_time is None:
        return None
    return convert_epoch_to_local_datetime(latest_transaction_block_time)


def fetch_solana_native_balance_lamports(rpc_url: str, wallet_address: str) -> Optional[int]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet_address],
    }
    response_json = _rpc_post(rpc_url, payload)
    if response_json is None:
        for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
            response_json = _rpc_post(fallback_url, payload)
            if response_json is not None:
                break
    if response_json is None:
        logger.warning(
            "[BLOCKCHAIN][SOL][RPC] getBalance failed across all endpoints — "
            "wallet_address=%s reason=rpc_endpoints_exhausted",
            wallet_address,
        )
        return None
    result_payload = response_json.get("result")
    if not isinstance(result_payload, dict):
        return None
    lamports_value = result_payload.get("value")
    if lamports_value is None:
        return None
    return int(lamports_value)


def format_lamports_as_sol_text(lamports: int) -> str:
    return f"{float(lamports) / 1_000_000_000.0:.6f} SOL"


def fetch_solana_native_balance_lamports_across_endpoints(
        rpc_url: str,
        wallet_address: str,
) -> Optional[int]:
    candidate_rpc_urls: list[str] = [rpc_url]
    for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
        if fallback_url not in candidate_rpc_urls:
            candidate_rpc_urls.append(fallback_url)

    highest_lamports: Optional[int] = None
    for candidate_rpc_url in candidate_rpc_urls:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [wallet_address],
        }
        response_json = _rpc_post(candidate_rpc_url, payload)
        if response_json is None:
            continue
        result_payload = response_json.get("result")
        if not isinstance(result_payload, dict):
            continue
        lamports_value = result_payload.get("value")
        if lamports_value is None:
            continue
        parsed_lamports = int(lamports_value)
        if highest_lamports is None or parsed_lamports > highest_lamports:
            highest_lamports = parsed_lamports
    return highest_lamports


def poll_solana_native_balance_after_increase(
        rpc_url: str,
        wallet_address: str,
        balance_before_lamports: int,
        timeout_seconds: float = SOLANA_NATIVE_BALANCE_POLL_TIMEOUT_SECONDS,
        poll_interval_seconds: float = SOLANA_NATIVE_BALANCE_POLL_INTERVAL_SECONDS,
) -> Optional[int]:
    deadline_timestamp = time.monotonic() + timeout_seconds
    last_observed_lamports: Optional[int] = None
    poll_attempt_count = 0
    invalidate_rpc_cache_for_chain(BlockchainNetwork.SOLANA)

    while time.monotonic() < deadline_timestamp:
        poll_attempt_count += 1
        current_lamports = fetch_solana_native_balance_lamports_across_endpoints(rpc_url, wallet_address)
        if current_lamports is not None:
            last_observed_lamports = current_lamports
            if current_lamports > balance_before_lamports:
                logger.debug(
                    "[BLOCKCHAIN][SOL][RPC] Balance polling detected increase — "
                    "wallet_address=%s poll_attempt_count=%d balance_before_lamports=%d balance_after_lamports=%d",
                    wallet_address,
                    poll_attempt_count,
                    balance_before_lamports,
                    current_lamports,
                )
                return current_lamports
        time.sleep(poll_interval_seconds)

    logger.debug(
        "[BLOCKCHAIN][SOL][RPC] Balance polling completed without increase — "
        "wallet_address=%s poll_attempt_count=%d balance_before_lamports=%d last_observed_lamports=%s",
        wallet_address,
        poll_attempt_count,
        balance_before_lamports,
        str(last_observed_lamports),
    )
    return last_observed_lamports


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
