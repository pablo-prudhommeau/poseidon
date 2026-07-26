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


class RaydiumCpmmPoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 232
    ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH = 8
    TOKEN_ZERO_VAULT_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 64
    TOKEN_ONE_VAULT_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 96
    TOKEN_ZERO_MINT_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 160
    TOKEN_ONE_MINT_BYTE_OFFSET = ANCHOR_ACCOUNT_DISCRIMINATOR_LENGTH + 192

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
                    "[BLOCKCHAIN][PRICE][SOL][RAYDIUM][CPMM]",
            ):
                return None

            token_mint_zero = read_pubkey_base58_at_offset(
                account_data,
                self.TOKEN_ZERO_MINT_BYTE_OFFSET,
            )
            token_mint_one = read_pubkey_base58_at_offset(
                account_data,
                self.TOKEN_ONE_MINT_BYTE_OFFSET,
            )
            token_vault_zero = read_pubkey_base58_at_offset(
                account_data,
                self.TOKEN_ZERO_VAULT_BYTE_OFFSET,
            )
            token_vault_one = read_pubkey_base58_at_offset(
                account_data,
                self.TOKEN_ONE_VAULT_BYTE_OFFSET,
            )

            return resolve_two_sided_pool_price_from_vaults(
                rpc_url=rpc_url,
                target_token_address=target_token_address,
                token_mint_a=token_mint_zero,
                token_mint_b=token_mint_one,
                vault_address_a=token_vault_zero,
                vault_address_b=token_vault_one,
            )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][CPMM] Error parsing pool data")
            return None
