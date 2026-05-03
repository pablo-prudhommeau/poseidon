from __future__ import annotations

import struct
from typing import Optional

from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_PUMPFUN_TOKEN_DECIMALS,
    SOLANA_SOL_DECIMALS,
    SOLANA_WRAPPED_SOL_MINT,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class PumpfunPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 24

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[tuple[float, str]]:
        if len(account_data) < self.MINIMUM_ACCOUNT_DATA_LENGTH:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPFUN] Account data too short (%d bytes)", len(account_data))
            return None

        virtual_token_reserves = struct.unpack_from("<Q", account_data, 8)[0]
        virtual_sol_reserves = struct.unpack_from("<Q", account_data, 16)[0]

        if virtual_token_reserves <= 0 or virtual_sol_reserves <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][PUMPFUN] Zero or negative reserves")
            return None

        adjusted_sol_reserves = virtual_sol_reserves / (10 ** SOLANA_SOL_DECIMALS)
        adjusted_token_reserves = virtual_token_reserves / (10 ** SOLANA_PUMPFUN_TOKEN_DECIMALS)
        price_in_sol = adjusted_sol_reserves / adjusted_token_reserves

        return price_in_sol, SOLANA_WRAPPED_SOL_MINT
