from __future__ import annotations

from typing import Optional

import base58

from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class OrcaPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 653

    SQRT_PRICE_OFFSET = 61
    TICK_CURRENT_INDEX_OFFSET = 77
    TICK_SPACING_OFFSET = 81

    REWARD_INFO_SIZE = 128
    REWARD_INFO_COUNT = 3

    TOKEN_MINT_A_OFFSET = 101 + (REWARD_INFO_SIZE * REWARD_INFO_COUNT)
    TOKEN_VAULT_A_OFFSET = TOKEN_MINT_A_OFFSET + 32
    FEE_GROWTH_A_OFFSET = TOKEN_VAULT_A_OFFSET + 32
    TOKEN_MINT_B_OFFSET = FEE_GROWTH_A_OFFSET + 16

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[tuple[float, str]]:
        if len(account_data) < self.MINIMUM_ACCOUNT_DATA_LENGTH:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][ORCA] Account data too short (%d bytes)", len(account_data))
            return None

        sqrt_price = int.from_bytes(
            account_data[self.SQRT_PRICE_OFFSET:self.SQRT_PRICE_OFFSET + 16],
            "little",
        )
        if sqrt_price <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][ORCA] Zero sqrtPrice")
            return None

        if len(account_data) < self.TOKEN_MINT_B_OFFSET + 32:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][ORCA] Account data too short for mint extraction (%d bytes)", len(account_data))
            return None

        token_mint_a = base58.b58encode(account_data[self.TOKEN_MINT_A_OFFSET:self.TOKEN_MINT_A_OFFSET + 32]).decode("ascii")
        token_mint_b = base58.b58encode(account_data[self.TOKEN_MINT_B_OFFSET:self.TOKEN_MINT_B_OFFSET + 32]).decode("ascii")

        decimals_a = get_spl_token_decimals(rpc_url, token_mint_a)
        decimals_b = get_spl_token_decimals(rpc_url, token_mint_b)

        raw_price = (sqrt_price / (2 ** 64)) ** 2
        adjusted_price = raw_price * (10 ** (decimals_a - decimals_b))

        target_is_a = target_token_address == token_mint_a
        if target_is_a:
            return adjusted_price, token_mint_b
        if adjusted_price <= 0:
            return None
        return 1.0 / adjusted_price, token_mint_a
