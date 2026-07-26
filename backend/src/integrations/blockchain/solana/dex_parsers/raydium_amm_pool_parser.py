from __future__ import annotations

from typing import Optional

from src.integrations.blockchain.solana.dex_parsers.raydium_clmm_pool_parser import RaydiumClmmPoolParser
from src.integrations.blockchain.solana.dex_parsers.raydium_cpmm_pool_parser import RaydiumCpmmPoolParser
from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    ensure_account_data_length,
    read_pubkey_base58_at_offset,
    resolve_two_sided_pool_price_from_vaults,
)
from src.integrations.blockchain.solana.solana_structures import SolanaPoolParsedPrice
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

RAYDIUM_AMM_V4_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_CLMM_PROGRAM_ID = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
RAYDIUM_CPMM_PROGRAM_ID = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"


class RaydiumAmmV4PoolParser:
    MINIMUM_ACCOUNT_DATA_LENGTH = 464
    BASE_VAULT_BYTE_OFFSET = 336
    QUOTE_VAULT_BYTE_OFFSET = 368
    BASE_MINT_BYTE_OFFSET = 400
    QUOTE_MINT_BYTE_OFFSET = 432

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
                    "[BLOCKCHAIN][PRICE][SOL][RAYDIUM][AMM]",
            ):
                return None

            base_mint = read_pubkey_base58_at_offset(account_data, self.BASE_MINT_BYTE_OFFSET)
            quote_mint = read_pubkey_base58_at_offset(account_data, self.QUOTE_MINT_BYTE_OFFSET)
            base_vault = read_pubkey_base58_at_offset(account_data, self.BASE_VAULT_BYTE_OFFSET)
            quote_vault = read_pubkey_base58_at_offset(account_data, self.QUOTE_VAULT_BYTE_OFFSET)

            return resolve_two_sided_pool_price_from_vaults(
                rpc_url=rpc_url,
                target_token_address=target_token_address,
                token_mint_a=base_mint,
                token_mint_b=quote_mint,
                vault_address_a=base_vault,
                vault_address_b=quote_vault,
            )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][AMM] Error parsing pool data")
            return None


class RaydiumAmmPoolParser:
    def __init__(self) -> None:
        self._amm_v4_parser = RaydiumAmmV4PoolParser()
        self._clmm_parser = RaydiumClmmPoolParser()
        self._cpmm_parser = RaydiumCpmmPoolParser()

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[SolanaPoolParsedPrice]:
        if owner_program == RAYDIUM_CLMM_PROGRAM_ID:
            return self._clmm_parser.parse_pool_price(
                rpc_url,
                account_data,
                target_token_address,
                owner_program,
            )
        if owner_program == RAYDIUM_CPMM_PROGRAM_ID:
            return self._cpmm_parser.parse_pool_price(
                rpc_url,
                account_data,
                target_token_address,
                owner_program,
            )
        if not owner_program:
            logger.debug(
                "[BLOCKCHAIN][PRICE][SOL][RAYDIUM] Missing program owner — refusing AMM v4 fallback",
            )
            return None

        if owner_program == RAYDIUM_AMM_V4_PROGRAM_ID:
            return self._amm_v4_parser.parse_pool_price(
                rpc_url,
                account_data,
                target_token_address,
                owner_program,
            )

        logger.debug(
            "[BLOCKCHAIN][PRICE][SOL][RAYDIUM] Unsupported Raydium program owner %s",
            owner_program,
        )
        return None
