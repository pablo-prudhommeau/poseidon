from __future__ import annotations

from typing import Optional

from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    ensure_account_data_length,
    read_pubkey_base58_at_offset,
    resolve_two_sided_pool_price_from_vaults,
)
from src.integrations.blockchain.solana.solana_structures import SolanaPoolParsedPrice
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class PumpswapPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 203
    TOKEN_MINT_BYTE_OFFSET = 43
    SOL_MINT_BYTE_OFFSET = 75
    TOKEN_VAULT_BYTE_OFFSET = 139
    SOL_VAULT_BYTE_OFFSET = 171

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
                    "[BLOCKCHAIN][PRICE][SOL][PUMPSWAP]",
            ):
                return None

            token_mint = read_pubkey_base58_at_offset(account_data, self.TOKEN_MINT_BYTE_OFFSET)
            sol_mint = read_pubkey_base58_at_offset(account_data, self.SOL_MINT_BYTE_OFFSET)
            token_vault = read_pubkey_base58_at_offset(account_data, self.TOKEN_VAULT_BYTE_OFFSET)
            sol_vault = read_pubkey_base58_at_offset(account_data, self.SOL_VAULT_BYTE_OFFSET)

            return resolve_two_sided_pool_price_from_vaults(
                rpc_url=rpc_url,
                target_token_address=target_token_address,
                token_mint_a=token_mint,
                token_mint_b=sol_mint,
                vault_address_a=token_vault,
                vault_address_b=sol_vault,
            )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SOL][PUMPSWAP] Error parsing pool data")
            return None
