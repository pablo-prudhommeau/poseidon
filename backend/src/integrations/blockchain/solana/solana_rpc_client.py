from __future__ import annotations

import base64
import struct
import time
from datetime import datetime
from typing import Optional

import requests

from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import convert_epoch_to_local_datetime
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.blockchain_rpc_registry import (
    invalidate_rpc_cache_for_chain,
    list_fallback_rpc_urls_for_chain,
    resolve_rpc_url_for_chain,
)
from src.integrations.blockchain.solana.solana_rpc_rate_limiter_service import (
    register_rpc_failure_backoff,
    wait_before_rpc_request,
)
from src.integrations.blockchain.solana.solana_structures import SolanaRpcFailureReason
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_KNOWN_STABLECOIN_MINTS,
    SOLANA_SPL_TOKEN_BALANCE_OFFSET,
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
SOLANA_MULTIPLE_ACCOUNTS_CHUNK_SIZE = 10

SOLANA_SOL_USDC_REFERENCE_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"

_cached_sol_usd_price: Optional[float] = None
_cached_sol_usd_timestamp: float = 0.0

_spl_decimals_cache: dict[str, int] = {}


def get_solana_rpc_url() -> str:
    return resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)


def solana_rpc_post(rpc_url: str, payload: dict) -> dict:
    rpc_method = str(payload.get("method", "unknown"))
    wait_before_rpc_request(rpc_url)
    try:
        response = requests.post(
            rpc_url,
            json=payload,
            timeout=SOLANA_RPC_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json"},
        )
    except requests.exceptions.Timeout as timeout_error:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] RPC request timeout — rpc_method=%s rpc_url=%s",
            rpc_method,
            rpc_url,
        )
        raise BlockchainRpcUnavailableError(
            f"[BLOCKCHAIN][SOL][RPC] Timeout for {rpc_method}",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method=rpc_method,
            failure_reason=SolanaRpcFailureReason.TIMEOUT,
            rpc_url=rpc_url,
        ) from timeout_error
    except requests.exceptions.RequestException as network_error:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] RPC network error — rpc_method=%s rpc_url=%s error=%s",
            rpc_method,
            rpc_url,
            str(network_error),
        )
        raise BlockchainRpcUnavailableError(
            f"[BLOCKCHAIN][SOL][RPC] Network error for {rpc_method}",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method=rpc_method,
            failure_reason=SolanaRpcFailureReason.NETWORK_ERROR,
            rpc_url=rpc_url,
        ) from network_error

    if response.status_code == 429:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] RPC request rate-limited — rpc_method=%s rpc_url=%s http_status=429",
            rpc_method,
            rpc_url,
        )
        register_rpc_failure_backoff(rpc_url, SolanaRpcFailureReason.RATE_LIMITED)
        raise BlockchainRpcUnavailableError(
            f"[BLOCKCHAIN][SOL][RPC] HTTP 429 for {rpc_method}",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method=rpc_method,
            failure_reason=SolanaRpcFailureReason.RATE_LIMITED,
            rpc_url=rpc_url,
        )

    if response.status_code != 200:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] RPC request failed with non-200 status — "
            "rpc_method=%s rpc_url=%s http_status=%d",
            rpc_method,
            rpc_url,
            response.status_code,
        )
        raise BlockchainRpcUnavailableError(
            f"[BLOCKCHAIN][SOL][RPC] HTTP {response.status_code} for {rpc_method}",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method=rpc_method,
            failure_reason=SolanaRpcFailureReason.HTTP_ERROR,
            rpc_url=rpc_url,
        )

    response_json = response.json()
    error_payload = response_json.get("error")
    if error_payload is not None:
        error_code = 0
        if isinstance(error_payload, dict):
            error_code = int(error_payload.get("code", 0))
        if error_code == 429:
            register_rpc_failure_backoff(rpc_url, SolanaRpcFailureReason.RATE_LIMITED)
            raise BlockchainRpcUnavailableError(
                f"[BLOCKCHAIN][SOL][RPC] JSON-RPC 429 for {rpc_method}",
                blockchain_network=BlockchainNetwork.SOLANA,
                rpc_method=rpc_method,
                failure_reason=SolanaRpcFailureReason.RATE_LIMITED,
                rpc_url=rpc_url,
            )
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] JSON-RPC error — rpc_method=%s rpc_url=%s error=%s",
            rpc_method,
            rpc_url,
            str(error_payload),
        )
        raise BlockchainRpcUnavailableError(
            f"[BLOCKCHAIN][SOL][RPC] JSON-RPC error for {rpc_method}",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method=rpc_method,
            failure_reason=SolanaRpcFailureReason.JSON_RPC_ERROR,
            rpc_url=rpc_url,
        )

    return response_json


def execute_solana_rpc_with_endpoint_fallbacks(rpc_url: str, payload: dict) -> dict:
    rpc_method = str(payload.get("method", "unknown"))
    candidate_urls: list[str] = [rpc_url]
    for fallback_url in list_fallback_rpc_urls_for_chain(BlockchainNetwork.SOLANA, rpc_url):
        if fallback_url not in candidate_urls:
            candidate_urls.append(fallback_url)

    last_rate_limit_error: Optional[BlockchainRpcUnavailableError] = None
    last_infrastructure_error: Optional[BlockchainRpcUnavailableError] = None

    for candidate_url in candidate_urls:
        try:
            return solana_rpc_post(candidate_url, payload)
        except BlockchainRpcUnavailableError as rpc_unavailable_error:
            if rpc_unavailable_error.failure_reason == SolanaRpcFailureReason.RATE_LIMITED:
                last_rate_limit_error = rpc_unavailable_error
                continue
            last_infrastructure_error = rpc_unavailable_error
            continue

    if last_rate_limit_error is not None:
        raise last_rate_limit_error

    if last_infrastructure_error is not None:
        raise last_infrastructure_error

    raise BlockchainRpcUnavailableError(
        f"[BLOCKCHAIN][SOL][RPC] All endpoints exhausted for {rpc_method}",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method=rpc_method,
        failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
        rpc_url=rpc_url,
    )


def _invalidate_solana_rpc_cache_after_endpoints_exhausted() -> None:
    invalidate_rpc_cache_for_chain(BlockchainNetwork.SOLANA)


def rpc_get_account_info(rpc_url: str, account_address: str) -> Optional[dict]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [account_address, {"encoding": "base64"}],
    }

    try:
        response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
    except BlockchainRpcUnavailableError:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] getAccountInfo unavailable — account_address_prefix=%s",
            account_address[:12],
        )
        _invalidate_solana_rpc_cache_after_endpoints_exhausted()
        raise

    result = response_json.get("result")
    if result is None:
        return None
    return result.get("value")


def rpc_get_account_info_json_parsed(rpc_url: str, account_address: str) -> Optional[dict]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [account_address, {"encoding": "jsonParsed"}],
    }

    try:
        response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
    except BlockchainRpcUnavailableError:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] getAccountInfo jsonParsed unavailable — account_address_prefix=%s",
            account_address[:12],
        )
        _invalidate_solana_rpc_cache_after_endpoints_exhausted()
        raise

    result = response_json.get("result")
    if result is None:
        return None
    return result.get("value")


def rpc_get_multiple_accounts_json_parsed(rpc_url: str, account_addresses: list[str]) -> list[Optional[dict]]:
    if not account_addresses:
        return []

    all_results: list[Optional[dict]] = []

    for chunk_start_index in range(0, len(account_addresses), SOLANA_MULTIPLE_ACCOUNTS_CHUNK_SIZE):
        chunk = account_addresses[chunk_start_index:chunk_start_index + SOLANA_MULTIPLE_ACCOUNTS_CHUNK_SIZE]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getMultipleAccounts",
            "params": [chunk, {"encoding": "jsonParsed"}],
        }

        try:
            response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
        except BlockchainRpcUnavailableError:
            logger.debug(
                "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts jsonParsed unavailable — chunk_account_count=%d",
                len(chunk),
            )
            _invalidate_solana_rpc_cache_after_endpoints_exhausted()
            raise

        result = response_json.get("result")
        if result is None:
            raise BlockchainRpcUnavailableError(
                "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts jsonParsed missing result payload",
                blockchain_network=BlockchainNetwork.SOLANA,
                rpc_method="getMultipleAccounts",
                failure_reason=SolanaRpcFailureReason.JSON_RPC_ERROR,
                rpc_url=rpc_url,
            )

        chunk_result = result.get("value")
        if chunk_result is None:
            raise BlockchainRpcUnavailableError(
                "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts jsonParsed missing value payload",
                blockchain_network=BlockchainNetwork.SOLANA,
                rpc_method="getMultipleAccounts",
                failure_reason=SolanaRpcFailureReason.JSON_RPC_ERROR,
                rpc_url=rpc_url,
            )

        all_results.extend(chunk_result)

    return all_results


def rpc_get_multiple_accounts(rpc_url: str, account_addresses: list[str]) -> list[Optional[dict]]:
    if not account_addresses:
        return []

    all_results: list[Optional[dict]] = []

    for chunk_start_index in range(0, len(account_addresses), SOLANA_MULTIPLE_ACCOUNTS_CHUNK_SIZE):
        chunk = account_addresses[chunk_start_index:chunk_start_index + SOLANA_MULTIPLE_ACCOUNTS_CHUNK_SIZE]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getMultipleAccounts",
            "params": [chunk, {"encoding": "base64"}],
        }

        try:
            response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
        except BlockchainRpcUnavailableError:
            logger.debug(
                "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts unavailable — chunk_account_count=%d",
                len(chunk),
            )
            _invalidate_solana_rpc_cache_after_endpoints_exhausted()
            raise

        result = response_json.get("result")
        if result is None:
            raise BlockchainRpcUnavailableError(
                "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts missing result payload",
                blockchain_network=BlockchainNetwork.SOLANA,
                rpc_method="getMultipleAccounts",
                failure_reason=SolanaRpcFailureReason.JSON_RPC_ERROR,
                rpc_url=rpc_url,
            )

        chunk_result = result.get("value")
        if chunk_result is None:
            raise BlockchainRpcUnavailableError(
                "[BLOCKCHAIN][SOL][RPC] getMultipleAccounts missing value payload",
                blockchain_network=BlockchainNetwork.SOLANA,
                rpc_method="getMultipleAccounts",
                failure_reason=SolanaRpcFailureReason.JSON_RPC_ERROR,
                rpc_url=rpc_url,
            )

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


def read_spl_token_balance_from_account_info(account_info: dict) -> Optional[int]:
    account_data = decode_account_data(account_info)
    if account_data is None or len(account_data) < 72:
        return None
    return struct.unpack_from("<Q", account_data, SOLANA_SPL_TOKEN_BALANCE_OFFSET)[0]


def fetch_spl_token_balance(rpc_url: str, vault_address: str) -> Optional[int]:
    account_info = rpc_get_account_info(rpc_url, vault_address)
    if account_info is None:
        return None
    return read_spl_token_balance_from_account_info(account_info)


def fetch_spl_token_balance_for_wallet_and_mint(
        rpc_url: str,
        wallet_address: str,
        token_mint_address: str,
) -> int:
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
    try:
        response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
    except BlockchainRpcUnavailableError:
        logger.debug(
            "[BLOCKCHAIN][SOL][RPC] getMinimumBalanceForRentExemption unavailable — account_data_length=%d",
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
    infrastructure_failure_count = 0

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
        try:
            response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
        except BlockchainRpcUnavailableError:
            infrastructure_failure_count += 1
            logger.debug(
                "[BLOCKCHAIN][SOL][RPC] getTokenAccountsByOwner unavailable — "
                "wallet_address=%s owner_program_id=%s",
                wallet_address,
                supported_program_id,
            )
            continue

        fetched_entries = response_json.get("result", {}).get("value", [])
        if isinstance(fetched_entries, list):
            token_account_entries.extend(fetched_entries)

    if infrastructure_failure_count == len(supported_program_ids):
        _invalidate_solana_rpc_cache_after_endpoints_exhausted()
        raise BlockchainRpcUnavailableError(
            "[BLOCKCHAIN][SOL][RPC] getTokenAccountsByOwner failed across all owner programs",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="getTokenAccountsByOwner",
            failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
            rpc_url=rpc_url,
        )

    if infrastructure_failure_count > 0:
        _invalidate_solana_rpc_cache_after_endpoints_exhausted()
        raise BlockchainRpcUnavailableError(
            "[BLOCKCHAIN][SOL][RPC] getTokenAccountsByOwner partially unavailable",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="getTokenAccountsByOwner",
            failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
            rpc_url=rpc_url,
        )

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
        account_state = str(account_info.get("state", "initialized"))
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
                account_state=account_state,
            )
        )
    return parsed_accounts


def resolve_wallet_token_account_transfer_blocked(
        rpc_url: str,
        wallet_address: str,
        token_mint_address: str,
) -> bool:
    token_accounts = list_wallet_spl_token_accounts(rpc_url, wallet_address)
    for token_account in token_accounts:
        if token_account.token_mint_address != token_mint_address:
            continue
        return token_account.account_state.strip().lower() == "frozen"
    return False


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

    try:
        response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
    except BlockchainRpcUnavailableError:
        raise

    signature_entries = response_json.get("result")
    if not isinstance(signature_entries, list) or not signature_entries:
        return None

    block_time_value = signature_entries[0].get("blockTime")
    if block_time_value is None:
        return None
    return int(block_time_value)


def fetch_token_account_last_activity_datetime(
        rpc_url: str,
        token_account_address: str,
) -> Optional[datetime]:
    latest_transaction_block_time = rpc_get_latest_confirmed_transaction_block_time(rpc_url, token_account_address)
    if latest_transaction_block_time is None:
        return None
    return convert_epoch_to_local_datetime(latest_transaction_block_time)


def fetch_solana_native_balance_lamports(rpc_url: str, wallet_address: str) -> int:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet_address],
    }
    response_json = execute_solana_rpc_with_endpoint_fallbacks(rpc_url, payload)
    result_payload = response_json.get("result")
    if not isinstance(result_payload, dict):
        raise BlockchainRpcUnavailableError(
            "[BLOCKCHAIN][SOL][RPC] getBalance missing result payload",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="getBalance",
            failure_reason=SolanaRpcFailureReason.JSON_RPC_ERROR,
            rpc_url=rpc_url,
        )
    lamports_value = result_payload.get("value")
    if lamports_value is None:
        raise BlockchainRpcUnavailableError(
            "[BLOCKCHAIN][SOL][RPC] getBalance missing lamports value",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="getBalance",
            failure_reason=SolanaRpcFailureReason.JSON_RPC_ERROR,
            rpc_url=rpc_url,
        )
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
        try:
            parsed_lamports = fetch_solana_native_balance_lamports(candidate_rpc_url, wallet_address)
        except BlockchainRpcUnavailableError:
            continue
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
    _invalidate_solana_rpc_cache_after_endpoints_exhausted()

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


def get_spl_token_decimals(rpc_url: str, mint_address: str) -> int:
    cached_value = _spl_decimals_cache.get(mint_address)
    if cached_value is not None:
        return cached_value
    account_info = rpc_get_account_info(rpc_url, mint_address)
    if account_info is None:
        raise BlockchainRpcUnavailableError(
            f"[BLOCKCHAIN][SOL][RPC] Mint account missing for getMintDecimals — mint_address_prefix={mint_address[:12]}",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="getAccountInfo",
            failure_reason=SolanaRpcFailureReason.MISSING_ACCOUNT,
            rpc_url=rpc_url,
        )
    account_data = decode_account_data(account_info)
    if account_data is None or len(account_data) < 45:
        raise BlockchainRpcUnavailableError(
            f"[BLOCKCHAIN][SOL][RPC] Mint account data invalid for getMintDecimals — mint_address_prefix={mint_address[:12]}",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="getAccountInfo",
            failure_reason=SolanaRpcFailureReason.INVALID_ACCOUNT_DATA,
            rpc_url=rpc_url,
        )
    fetched_decimals = struct.unpack_from("<B", account_data, 44)[0]
    _spl_decimals_cache[mint_address] = fetched_decimals
    return fetched_decimals


def prefetch_spl_token_balances_for_vault_addresses(
        rpc_url: str,
        vault_addresses: list[str],
) -> dict[str, int]:
    unique_vault_addresses = list(dict.fromkeys(vault_addresses))
    if not unique_vault_addresses:
        return {}

    account_infos = rpc_get_multiple_accounts(rpc_url, unique_vault_addresses)
    balances_by_vault_address: dict[str, int] = {}
    for vault_address, account_info in zip(unique_vault_addresses, account_infos, strict=True):
        if account_info is None:
            continue
        balance_raw = read_spl_token_balance_from_account_info(account_info)
        if balance_raw is None:
            continue
        balances_by_vault_address[vault_address] = balance_raw
    return balances_by_vault_address


def prefetch_spl_token_decimals_for_mint_addresses(
        rpc_url: str,
        mint_addresses: list[str],
) -> dict[str, int]:
    decimals_by_mint_address: dict[str, int] = {}
    for mint_address in dict.fromkeys(mint_addresses):
        cached_value = _spl_decimals_cache.get(mint_address)
        if cached_value is not None:
            decimals_by_mint_address[mint_address] = cached_value
            continue
        try:
            fetched_decimals = get_spl_token_decimals(rpc_url, mint_address)
        except BlockchainRpcUnavailableError:
            continue
        decimals_by_mint_address[mint_address] = fetched_decimals
    return decimals_by_mint_address


def resolve_sol_usd_price(rpc_url: str) -> Optional[float]:
    global _cached_sol_usd_price, _cached_sol_usd_timestamp

    now = time.monotonic()
    if _cached_sol_usd_price is not None and (now - _cached_sol_usd_timestamp) < SOLANA_SOL_USD_CACHE_TTL_SECONDS:
        return _cached_sol_usd_price

    from src.integrations.blockchain.solana.dex_parsers.raydium_pool_parser import RaydiumPoolParser
    from src.integrations.blockchain.solana.solana_structures import SOLANA_DEX_PROGRAM_IDS

    try:
        account_info = rpc_get_account_info(rpc_url, SOLANA_SOL_USDC_REFERENCE_POOL)
    except BlockchainRpcUnavailableError:
        logger.debug("[BLOCKCHAIN][PRICE][SOL][REFERENCE] SOL/USDC reference pool RPC unavailable")
        return _cached_sol_usd_price

    if account_info is None:
        logger.debug("[BLOCKCHAIN][PRICE][SOL][REFERENCE] SOL/USDC reference pool account missing")
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
        logger.debug("[BLOCKCHAIN][PRICE][SOL][REFERENCE] Cannot parse SOL/USDC reference pool")
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
