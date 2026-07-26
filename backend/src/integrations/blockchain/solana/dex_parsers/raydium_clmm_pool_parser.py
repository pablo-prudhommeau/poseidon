from __future__ import annotations

from typing import Optional

from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    ensure_account_data_length,
    read_pubkey_base58_at_offset,
    read_unsigned_128_at_offset,
    resolve_sqrt_price_x64_pool_price,
)
from src.integrations.blockchain.solana.solana_structures import SolanaPoolParsedPrice
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class RaydiumClmmPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 269
    ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH = 8
    TOKEN_MINT_ZERO_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 65
    TOKEN_MINT_ONE_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 97
    MINT_DECIMALS_ZERO_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 225
    MINT_DECIMALS_ONE_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 226
    SQRT_PRICE_X64_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 245

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
                    "[BLOCKCHAIN][PRICE][SOL][RAYDIUM][CLMM]",
            ):
                return None

            token_mint_zero = read_pubkey_base58_at_offset(
                account_data,
                self.TOKEN_MINT_ZERO_BYTE_OFFSET,
            )
            token_mint_one = read_pubkey_base58_at_offset(
                account_data,
                self.TOKEN_MINT_ONE_BYTE_OFFSET,
            )
            decimals_token_zero = account_data[self.MINT_DECIMALS_ZERO_BYTE_OFFSET]
            decimals_token_one = account_data[self.MINT_DECIMALS_ONE_BYTE_OFFSET]
            sqrt_price_x64 = read_unsigned_128_at_offset(
                account_data,
                self.SQRT_PRICE_X64_BYTE_OFFSET,
            )

            return resolve_sqrt_price_x64_pool_price(
                target_token_address=target_token_address,
                token_mint_0=token_mint_zero,
                token_mint_1=token_mint_one,
                sqrt_price_x64=sqrt_price_x64,
                decimals_token0=decimals_token_zero,
                decimals_token1=decimals_token_one,
            )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][CLMM] Error parsing pool data")
            return None
