from __future__ import annotations

import math
import struct
from typing import Optional

import base58

from src.integrations.blockchain.solana.solana_structures import (
    SolanaPoolParsedPrice,
    SolanaVaultBalanceDecimalsSnapshot,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SQRT_PRICE_Q64_DENOMINATOR = float(2**64)


def read_pubkey_base58_at_offset(account_data: bytes, byte_offset: int) -> str:
    return base58.b58encode(account_data[byte_offset:byte_offset + 32]).decode("ascii")


def read_unsigned_64_at_offset(account_data: bytes, byte_offset: int) -> int:
    return struct.unpack_from("<Q", account_data, byte_offset)[0]


def read_unsigned_128_at_offset(account_data: bytes, byte_offset: int) -> int:
    return int.from_bytes(account_data[byte_offset:byte_offset + 16], byteorder="little", signed=False)


def read_signed_32_at_offset(account_data: bytes, byte_offset: int) -> int:
    return struct.unpack_from("<i", account_data, byte_offset)[0]


def read_unsigned_16_at_offset(account_data: bytes, byte_offset: int) -> int:
    return struct.unpack_from("<H", account_data, byte_offset)[0]


def ensure_account_data_length(
        account_data: bytes,
        minimum_length: int,
        debug_log_prefix: str,
) -> bool:
    if len(account_data) < minimum_length:
        logger.debug(
            "%s Account data too short (%d bytes)",
            debug_log_prefix,
            len(account_data),
        )
        return False
    return True


def resolve_target_token_price_in_pair(
        target_token_address: str,
        token_mint_a: str,
        token_mint_b: str,
        price_of_a_in_b: float,
) -> Optional[SolanaPoolParsedPrice]:
    if not math.isfinite(price_of_a_in_b) or price_of_a_in_b <= 0.0:
        return None

    if target_token_address == token_mint_a:
        return SolanaPoolParsedPrice(
            price_in_quote_token=price_of_a_in_b,
            quote_token_mint=token_mint_b,
        )

    if target_token_address == token_mint_b:
        inverted_price = 1.0 / price_of_a_in_b
        if not math.isfinite(inverted_price) or inverted_price <= 0.0:
            return None
        return SolanaPoolParsedPrice(
            price_in_quote_token=inverted_price,
            quote_token_mint=token_mint_a,
        )

    return None


def fetch_vault_balances_and_mint_decimals(
        rpc_url: str,
        vault_address_a: str,
        vault_address_b: str,
        mint_address_a: str,
        mint_address_b: str,
) -> Optional[SolanaVaultBalanceDecimalsSnapshot]:
    from src.integrations.blockchain.solana.solana_rpc_client import (
        get_spl_token_decimals,
        read_spl_token_balance_from_account_info,
        rpc_get_multiple_accounts,
    )

    vault_accounts = rpc_get_multiple_accounts(rpc_url, [vault_address_a, vault_address_b])
    if len(vault_accounts) < 2:
        return None

    vault_account_a = vault_accounts[0]
    vault_account_b = vault_accounts[1]
    if vault_account_a is None or vault_account_b is None:
        return None

    vault_balance_a_raw = read_spl_token_balance_from_account_info(vault_account_a)
    vault_balance_b_raw = read_spl_token_balance_from_account_info(vault_account_b)
    if vault_balance_a_raw is None or vault_balance_b_raw is None:
        return None
    if vault_balance_a_raw <= 0 or vault_balance_b_raw <= 0:
        return None

    try:
        decimals_a = get_spl_token_decimals(rpc_url, mint_address_a)
        decimals_b = get_spl_token_decimals(rpc_url, mint_address_b)
    except Exception:
        logger.exception(
            "[BLOCKCHAIN][PRICE][SOL][UTILS] Failed to fetch mint decimals — mint_a=%s mint_b=%s",
            mint_address_a[:12],
            mint_address_b[:12],
        )
        return None

    return SolanaVaultBalanceDecimalsSnapshot(
        vault_balance_a_raw=vault_balance_a_raw,
        vault_balance_b_raw=vault_balance_b_raw,
        decimals_a=decimals_a,
        decimals_b=decimals_b,
    )


def resolve_two_sided_pool_price_from_reserves(
        target_token_address: str,
        token_mint_a: str,
        token_mint_b: str,
        reserve_a_raw: int,
        reserve_b_raw: int,
        decimals_a: int,
        decimals_b: int,
) -> Optional[SolanaPoolParsedPrice]:
    if reserve_a_raw <= 0 or reserve_b_raw <= 0:
        return None

    adjusted_reserve_a = reserve_a_raw / float(10 ** decimals_a)
    adjusted_reserve_b = reserve_b_raw / float(10 ** decimals_b)
    if adjusted_reserve_a <= 0.0 or adjusted_reserve_b <= 0.0:
        return None

    price_of_a_in_b = adjusted_reserve_b / adjusted_reserve_a
    return resolve_target_token_price_in_pair(
        target_token_address=target_token_address,
        token_mint_a=token_mint_a,
        token_mint_b=token_mint_b,
        price_of_a_in_b=price_of_a_in_b,
    )


def resolve_two_sided_pool_price_from_vaults(
        rpc_url: str,
        target_token_address: str,
        token_mint_a: str,
        token_mint_b: str,
        vault_address_a: str,
        vault_address_b: str,
) -> Optional[SolanaPoolParsedPrice]:
    vault_snapshot = fetch_vault_balances_and_mint_decimals(
        rpc_url=rpc_url,
        vault_address_a=vault_address_a,
        vault_address_b=vault_address_b,
        mint_address_a=token_mint_a,
        mint_address_b=token_mint_b,
    )
    if vault_snapshot is None:
        return None

    return resolve_two_sided_pool_price_from_reserves(
        target_token_address=target_token_address,
        token_mint_a=token_mint_a,
        token_mint_b=token_mint_b,
        reserve_a_raw=vault_snapshot.vault_balance_a_raw,
        reserve_b_raw=vault_snapshot.vault_balance_b_raw,
        decimals_a=vault_snapshot.decimals_a,
        decimals_b=vault_snapshot.decimals_b,
    )


def convert_sqrt_price_x64_to_token0_price_in_token1(
        sqrt_price_x64: int,
        decimals_token0: int,
        decimals_token1: int,
) -> Optional[float]:
    if sqrt_price_x64 <= 0:
        return None

    sqrt_price = float(sqrt_price_x64) / SQRT_PRICE_Q64_DENOMINATOR
    price_token1_per_token0_raw = sqrt_price * sqrt_price
    if not math.isfinite(price_token1_per_token0_raw) or price_token1_per_token0_raw <= 0.0:
        return None

    converted_price = price_token1_per_token0_raw * float(10 ** decimals_token0) / float(10 ** decimals_token1)
    if not math.isfinite(converted_price) or converted_price <= 0.0:
        return None
    return converted_price


def resolve_sqrt_price_x64_pool_price(
        target_token_address: str,
        token_mint_0: str,
        token_mint_1: str,
        sqrt_price_x64: int,
        decimals_token0: int,
        decimals_token1: int,
) -> Optional[SolanaPoolParsedPrice]:
    token0_price_in_token1 = convert_sqrt_price_x64_to_token0_price_in_token1(
        sqrt_price_x64=sqrt_price_x64,
        decimals_token0=decimals_token0,
        decimals_token1=decimals_token1,
    )
    if token0_price_in_token1 is None:
        return None

    return resolve_target_token_price_in_pair(
        target_token_address=target_token_address,
        token_mint_a=token_mint_0,
        token_mint_b=token_mint_1,
        price_of_a_in_b=token0_price_in_token1,
    )
