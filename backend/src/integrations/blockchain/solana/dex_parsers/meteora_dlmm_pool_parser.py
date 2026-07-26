from __future__ import annotations

import math
from typing import Optional

from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    ensure_account_data_length,
    read_pubkey_base58_at_offset,
    read_signed_32_at_offset,
    read_unsigned_16_at_offset,
    resolve_target_token_price_in_pair,
)
from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals
from src.integrations.blockchain.solana.solana_structures import SolanaPoolParsedPrice
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

METEORA_DLMM_BASIS_POINT_MAX = 10_000


class MeteoraDlmmPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 152
    ACTIVE_ID_BYTE_OFFSET = 76
    BIN_STEP_BYTE_OFFSET = 80
    TOKEN_X_MINT_BYTE_OFFSET = 88
    TOKEN_Y_MINT_BYTE_OFFSET = 120

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
                    "[BLOCKCHAIN][PRICE][SOL][METEORA][DLMM]",
            ):
                return None

            active_id = read_signed_32_at_offset(account_data, self.ACTIVE_ID_BYTE_OFFSET)
            bin_step = read_unsigned_16_at_offset(account_data, self.BIN_STEP_BYTE_OFFSET)
            if bin_step <= 0:
                logger.debug("[BLOCKCHAIN][PRICE][SOL][METEORA][DLMM] Invalid bin step")
                return None

            token_mint_x = read_pubkey_base58_at_offset(account_data, self.TOKEN_X_MINT_BYTE_OFFSET)
            token_mint_y = read_pubkey_base58_at_offset(account_data, self.TOKEN_Y_MINT_BYTE_OFFSET)

            try:
                decimals_token_x = get_spl_token_decimals(rpc_url, token_mint_x)
                decimals_token_y = get_spl_token_decimals(rpc_url, token_mint_y)
            except Exception:
                logger.exception(
                    "[BLOCKCHAIN][PRICE][SOL][METEORA][DLMM] Failed to fetch mint decimals — mint_x=%s mint_y=%s",
                    token_mint_x[:12],
                    token_mint_y[:12],
                )
                return None

            bin_price = (1.0 + (float(bin_step) / float(METEORA_DLMM_BASIS_POINT_MAX))) ** float(active_id)
            if not math.isfinite(bin_price) or bin_price <= 0.0:
                return None

            price_token_x_in_token_y = bin_price * float(10 ** (decimals_token_x - decimals_token_y))
            return resolve_target_token_price_in_pair(
                target_token_address=target_token_address,
                token_mint_a=token_mint_x,
                token_mint_b=token_mint_y,
                price_of_a_in_b=price_token_x_in_token_y,
            )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SOL][METEORA][DLMM] Error parsing pool data")
            return None
