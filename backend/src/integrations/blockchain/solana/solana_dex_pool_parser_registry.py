from __future__ import annotations

from typing import Optional

from src.integrations.blockchain.solana.solana_structures import (
    SolanaDexPoolPriceParser,
    SolanaOnchainPoolPriceParserBinding,
    SolanaOnchainPoolPriceParserRegistry,
)

ONCHAIN_POOL_PRICE_PARSER_DEX_IDS: tuple[str, ...] = (
    "meteora",
    "orca",
    "pumpfun",
    "pumpswap",
    "raydium",
    "raydium-clmm",
    "raydium-cpmm",
)

_onchain_pool_price_parser_registry: SolanaOnchainPoolPriceParserRegistry | None = None


def _resolve_onchain_pool_price_parser_registry() -> SolanaOnchainPoolPriceParserRegistry:
    global _onchain_pool_price_parser_registry
    if _onchain_pool_price_parser_registry is None:
        from src.integrations.blockchain.solana.dex_parsers.meteora_dlmm_pool_parser import MeteoraDlmmPoolParser
        from src.integrations.blockchain.solana.dex_parsers.orca_whirlpool_pool_parser import OrcaWhirlpoolPoolParser
        from src.integrations.blockchain.solana.dex_parsers.pumpfun_pool_parser import PumpfunPoolParser
        from src.integrations.blockchain.solana.dex_parsers.pumpswap_pool_parser import PumpswapPoolParser
        from src.integrations.blockchain.solana.dex_parsers.raydium_amm_pool_parser import RaydiumAmmPoolParser
        from src.integrations.blockchain.solana.dex_parsers.raydium_clmm_pool_parser import RaydiumClmmPoolParser
        from src.integrations.blockchain.solana.dex_parsers.raydium_cpmm_pool_parser import RaydiumCpmmPoolParser

        _onchain_pool_price_parser_registry = SolanaOnchainPoolPriceParserRegistry(
            bindings=[
                SolanaOnchainPoolPriceParserBinding(dex_identifier="pumpfun", parser=PumpfunPoolParser()),
                SolanaOnchainPoolPriceParserBinding(dex_identifier="pumpswap", parser=PumpswapPoolParser()),
                SolanaOnchainPoolPriceParserBinding(dex_identifier="raydium", parser=RaydiumAmmPoolParser()),
                SolanaOnchainPoolPriceParserBinding(dex_identifier="raydium-cpmm", parser=RaydiumCpmmPoolParser()),
                SolanaOnchainPoolPriceParserBinding(dex_identifier="raydium-clmm", parser=RaydiumClmmPoolParser()),
                SolanaOnchainPoolPriceParserBinding(dex_identifier="orca", parser=OrcaWhirlpoolPoolParser()),
                SolanaOnchainPoolPriceParserBinding(dex_identifier="meteora", parser=MeteoraDlmmPoolParser()),
            ],
        )
        registered_dex_identifiers = frozenset(_onchain_pool_price_parser_registry.dex_identifiers())
        declared_dex_identifiers = frozenset(ONCHAIN_POOL_PRICE_PARSER_DEX_IDS)
        if registered_dex_identifiers != declared_dex_identifiers:
            raise RuntimeError(
                "Solana on-chain pool price parser registry keys drifted from "
                f"ONCHAIN_POOL_PRICE_PARSER_DEX_IDS — declared={sorted(declared_dex_identifiers)} "
                f"registered={sorted(registered_dex_identifiers)}",
            )
    return _onchain_pool_price_parser_registry


def resolve_onchain_pool_price_parser_dex_ids() -> tuple[str, ...]:
    return ONCHAIN_POOL_PRICE_PARSER_DEX_IDS


def has_onchain_pool_price_parser_for_dex_id(dex_id: str) -> bool:
    return dex_id.strip().lower() in ONCHAIN_POOL_PRICE_PARSER_DEX_IDS


def resolve_onchain_pool_price_parser_for_dex_id(dex_id: str) -> Optional[SolanaDexPoolPriceParser]:
    return _resolve_onchain_pool_price_parser_registry().resolve_parser(dex_id)
