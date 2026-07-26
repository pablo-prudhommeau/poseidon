from __future__ import annotations

from typing import Optional

from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    ensure_account_data_length,
    read_pubkey_base58_at_offset,
    read_unsigned_128_at_offset,
    resolve_sqrt_price_x64_pool_price,
)
from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals
from src.integrations.blockchain.solana.solana_structures import SolanaPoolParsedPrice
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class OrcaWhirlpoolPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 245
    SQRT_PRICE_BYTE_OFFSET = 65
    TOKEN_MINT_A_BYTE_OFFSET = 101
    TOKEN_MINT_B_BYTE_OFFSET = 181

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[SolanaPoolParsedPrice]:
        try:
            if not ensure_account_data_length(
                    account_data,
                    self.MINIMUM_ACCOUNT_DATA_LENGTH,
                    "[BLOCKCHAIN][PRICE][SOL][ORCA]",
            ):
                return None

            token_mint_a = read_pubkey_base58_at_offset(account_data, self.TOKEN_MINT_A_BYTE_OFFSET)
            token_mint_b = read_pubkey_base58_at_offset(account_data, self.TOKEN_MINT_B_BYTE_OFFSET)
            sqrt_price_x64 = read_unsigned_128_at_offset(account_data, self.SQRT_PRICE_BYTE_OFFSET)

            try:
                decimals_token_a = get_spl_token_decimals(rpc_url, token_mint_a)
                decimals_token_b = get_spl_token_decimals(rpc_url, token_mint_b)
            except Exception:
                logger.exception(
                    "[BLOCKCHAIN][PRICE][SOL][ORCA] Failed to fetch mint decimals — mint_a=%s mint_b=%s",
                    token_mint_a[:12],
                    token_mint_b[:12],
                )
                return None

            return resolve_sqrt_price_x64_pool_price(
                target_token_address=target_token_address,
                token_mint_0=token_mint_a,
                token_mint_1=token_mint_b,
                sqrt_price_x64=sqrt_price_x64,
                decimals_token0=decimals_token_a,
                decimals_token1=decimals_token_b,
            )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SOL][ORCA] Error parsing pool data")
            return None
