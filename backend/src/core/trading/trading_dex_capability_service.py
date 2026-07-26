from __future__ import annotations

from src.core.trading.trading_chain_capability_service import resolve_trading_capabilities_snapshot

TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS: tuple[str, ...] = (
    "pumpfun",
    "pumpswap",
    "raydium",
    "raydium-clmm",
    "raydium-cpmm",
    "orca",
    "meteora",
)


def resolve_supported_trading_solana_dex_ids() -> list[str]:
    return list(resolve_trading_capabilities_snapshot().supported_solana_dex_identifiers)


def resolve_supported_trading_dex_identifiers() -> tuple[str, ...]:
    return tuple(resolve_supported_trading_solana_dex_ids())


def is_supported_trading_solana_dex_id(dex_id: str) -> bool:
    normalized_dex_id = dex_id.strip().lower()
    if not normalized_dex_id:
        return False
    for supported_dex_id in resolve_supported_trading_solana_dex_ids():
        if supported_dex_id == normalized_dex_id:
            return True
    return False
