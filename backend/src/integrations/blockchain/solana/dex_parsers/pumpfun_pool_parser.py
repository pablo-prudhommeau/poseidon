from __future__ import annotations

import math
from typing import Optional

from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    ensure_account_data_length,
    read_unsigned_64_at_offset,
)
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_PUMPFUN_TOKEN_DECIMALS,
    SOLANA_SOL_DECIMALS,
    SOLANA_WRAPPED_SOL_MINT,
    SolanaPoolParsedPrice,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class PumpfunPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 24
    VIRTUAL_TOKEN_RESERVES_BYTE_OFFSET = 8
    VIRTUAL_SOL_RESERVES_BYTE_OFFSET = 16

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[SolanaPoolParsedPrice]:
        if not ensure_account_data_length(
                account_data,
                self.MINIMUM_ACCOUNT_DATA_LENGTH,
                "[BLOCKCHAIN][PRICE][SOL][PUMPFUN]",
        ):
            return None

        virtual_token_reserves = read_unsigned_64_at_offset(
            account_data,
            self.VIRTUAL_TOKEN_RESERVES_BYTE_OFFSET,
        )
        virtual_sol_reserves = read_unsigned_64_at_offset(
            account_data,
            self.VIRTUAL_SOL_RESERVES_BYTE_OFFSET,
        )

        if virtual_token_reserves <= 0 or virtual_sol_reserves <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPFUN] Zero or negative reserves")
            return None

        adjusted_sol_reserves = virtual_sol_reserves / float(10 ** SOLANA_SOL_DECIMALS)
        adjusted_token_reserves = virtual_token_reserves / float(10 ** SOLANA_PUMPFUN_TOKEN_DECIMALS)
        price_in_sol = adjusted_sol_reserves / adjusted_token_reserves
        if not math.isfinite(price_in_sol) or price_in_sol <= 0.0:
            return None

        return SolanaPoolParsedPrice(
            price_in_quote_token=price_in_sol,
            quote_token_mint=SOLANA_WRAPPED_SOL_MINT,
        )
