from __future__ import annotations

from typing import Optional

import base58

from src.integrations.blockchain.solana.solana_structures import SolanaPriceParseResources
from src.integrations.blockchain.solana.solana_rpc_client import (
    fetch_spl_token_balance,
    get_spl_token_decimals,
)
from src.integrations.blockchain.solana.solana_structures import SOLANA_DEX_PROGRAM_IDS
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class RaydiumPoolParser:
    AMM_V4_MINIMUM_DATA_LENGTH = 168
    CLMM_MINIMUM_DATA_LENGTH = 337

    AMM_V4_BASE_MINT_OFFSET = 400
    AMM_V4_QUOTE_MINT_OFFSET = 432
    AMM_V4_BASE_VAULT_OFFSET = 336
    AMM_V4_QUOTE_VAULT_OFFSET = 368

    CLMM_TOKEN_MINT_0_OFFSET = 73
    CLMM_TOKEN_MINT_1_OFFSET = 105
    CLMM_SQRT_PRICE_X64_OFFSET = 253

    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
            parse_resources: SolanaPriceParseResources | None = None,
    ) -> Optional[tuple[float, str]]:
        if owner_program == SOLANA_DEX_PROGRAM_IDS["raydium_clmm"]:
            return self._parse_clmm_price(
                rpc_url,
                account_data,
                target_token_address,
                parse_resources=parse_resources,
            )
        return self._parse_amm_v4_price(
            rpc_url,
            account_data,
            target_token_address,
            parse_resources=parse_resources,
        )

    def _parse_amm_v4_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            parse_resources: SolanaPriceParseResources | None = None,
    ) -> Optional[tuple[float, str]]:
        if len(account_data) < self.AMM_V4_MINIMUM_DATA_LENGTH:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][V4] Account data too short (%d bytes)", len(account_data))
            return None

        base_mint = base58.b58encode(account_data[self.AMM_V4_BASE_MINT_OFFSET:self.AMM_V4_BASE_MINT_OFFSET + 32]).decode("ascii")
        quote_mint = base58.b58encode(account_data[self.AMM_V4_QUOTE_MINT_OFFSET:self.AMM_V4_QUOTE_MINT_OFFSET + 32]).decode("ascii")
        base_vault = base58.b58encode(account_data[self.AMM_V4_BASE_VAULT_OFFSET:self.AMM_V4_BASE_VAULT_OFFSET + 32]).decode("ascii")
        quote_vault = base58.b58encode(account_data[self.AMM_V4_QUOTE_VAULT_OFFSET:self.AMM_V4_QUOTE_VAULT_OFFSET + 32]).decode("ascii")

        base_balance = self._resolve_vault_balance_raw(
            rpc_url=rpc_url,
            vault_address=base_vault,
            parse_resources=parse_resources,
        )
        quote_balance = self._resolve_vault_balance_raw(
            rpc_url=rpc_url,
            vault_address=quote_vault,
            parse_resources=parse_resources,
        )
        if base_balance is None or quote_balance is None or base_balance <= 0 or quote_balance <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][V4] Invalid vault balances for %s", target_token_address[:8])
            return None

        base_decimals = self._resolve_mint_decimals(
            rpc_url=rpc_url,
            mint_address=base_mint,
            parse_resources=parse_resources,
        )
        quote_decimals = self._resolve_mint_decimals(
            rpc_url=rpc_url,
            mint_address=quote_mint,
            parse_resources=parse_resources,
        )
        if base_decimals is None or quote_decimals is None:
            return None

        adjusted_base = base_balance / (10 ** base_decimals)
        adjusted_quote = quote_balance / (10 ** quote_decimals)

        target_is_base = target_token_address == base_mint
        if target_is_base:
            return adjusted_quote / adjusted_base, quote_mint
        return adjusted_base / adjusted_quote, base_mint

    def _parse_clmm_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            parse_resources: SolanaPriceParseResources | None = None,
    ) -> Optional[tuple[float, str]]:
        if len(account_data) < self.CLMM_MINIMUM_DATA_LENGTH:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][CLMM] Account data too short (%d bytes)", len(account_data))
            return None

        sqrt_price_x64 = int.from_bytes(
            account_data[self.CLMM_SQRT_PRICE_X64_OFFSET:self.CLMM_SQRT_PRICE_X64_OFFSET + 16],
            "little",
        )
        if sqrt_price_x64 <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][CLMM] Zero sqrtPriceX64")
            return None

        token_mint_0 = base58.b58encode(account_data[self.CLMM_TOKEN_MINT_0_OFFSET:self.CLMM_TOKEN_MINT_0_OFFSET + 32]).decode("ascii")
        token_mint_1 = base58.b58encode(account_data[self.CLMM_TOKEN_MINT_1_OFFSET:self.CLMM_TOKEN_MINT_1_OFFSET + 32]).decode("ascii")

        decimals_0 = self._resolve_mint_decimals(
            rpc_url=rpc_url,
            mint_address=token_mint_0,
            parse_resources=parse_resources,
        )
        decimals_1 = self._resolve_mint_decimals(
            rpc_url=rpc_url,
            mint_address=token_mint_1,
            parse_resources=parse_resources,
        )

        if decimals_0 is None or decimals_1 is None:
            logger.debug("[BLOCKCHAIN][PRICE][SOL][RAYDIUM][CLMM] Failed to fetch decimals for %s or %s", token_mint_0[:8], token_mint_1[:8])
            return None

        raw_price = (sqrt_price_x64 / (2 ** 64)) ** 2
        adjusted_price = raw_price * (10 ** (decimals_0 - decimals_1))

        target_is_token_0 = target_token_address == token_mint_0
        if target_is_token_0:
            return adjusted_price, token_mint_1
        if adjusted_price <= 0:
            return None
        return 1.0 / adjusted_price, token_mint_0

    def _resolve_vault_balance_raw(
            self,
            rpc_url: str,
            vault_address: str,
            parse_resources: SolanaPriceParseResources | None,
    ) -> int | None:
        if parse_resources is not None:
            cached_balance = parse_resources.resolve_vault_balance_raw(vault_address)
            if cached_balance is not None:
                return cached_balance
        return fetch_spl_token_balance(rpc_url, vault_address)

    def _resolve_mint_decimals(
            self,
            rpc_url: str,
            mint_address: str,
            parse_resources: SolanaPriceParseResources | None,
    ) -> int | None:
        if parse_resources is not None:
            cached_decimals = parse_resources.resolve_mint_decimals(mint_address)
            if cached_decimals is not None:
                return cached_decimals
        return get_spl_token_decimals(rpc_url, mint_address)
