from __future__ import annotations

import struct
from typing import Optional

import base58

from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class MeteoraPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 104

    ACTIVE_ID_OFFSET = 76
    BIN_STEP_OFFSET = 80
    TOKEN_MINT_X_OFFSET = 88
    TOKEN_MINT_Y_OFFSET = 120

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[tuple[float, str]]:
        if len(account_data) < self.MINIMUM_ACCOUNT_DATA_LENGTH:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][METEORA] Account data too short (%d bytes)", len(account_data))
            return None

        active_id = struct.unpack_from("<i", account_data, self.ACTIVE_ID_OFFSET)[0]
        bin_step = struct.unpack_from("<H", account_data, self.BIN_STEP_OFFSET)[0]

        if len(account_data) < self.TOKEN_MINT_Y_OFFSET + 32:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][METEORA] Account data too short for mint extraction")
            return None

        token_mint_x = base58.b58encode(account_data[self.TOKEN_MINT_X_OFFSET:self.TOKEN_MINT_X_OFFSET + 32]).decode("ascii")
        token_mint_y = base58.b58encode(account_data[self.TOKEN_MINT_Y_OFFSET:self.TOKEN_MINT_Y_OFFSET + 32]).decode("ascii")

        decimals_x = get_spl_token_decimals(rpc_url, token_mint_x)
        decimals_y = get_spl_token_decimals(rpc_url, token_mint_y)

        if decimals_x is None or decimals_y is None:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][METEORA] Failed to fetch decimals for %s or %s", token_mint_x[:8], token_mint_y[:8])
            return None

        raw_price = (1.0 + bin_step / 10000.0) ** active_id
        adjusted_price = raw_price * (10 ** (decimals_x - decimals_y))

        target_is_token_x = target_token_address == token_mint_x
        if target_is_token_x:
            return adjusted_price, token_mint_y
        if adjusted_price <= 0:
            return None
        return 1.0 / adjusted_price, token_mint_x
