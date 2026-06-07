from __future__ import annotations

from src.core.trading.trading_structures import TradingConfigurationError

TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS: tuple[str, ...] = (
    "pumpfun",
    "pumpswap",
)

_effective_supported_trading_solana_dex_ids: tuple[str, ...] | None = None


def apply_supported_trading_solana_dex_configuration(supported_dex_ids: list[str]) -> None:
    global _effective_supported_trading_solana_dex_ids
    _effective_supported_trading_solana_dex_ids = tuple(supported_dex_ids)


def resolve_supported_trading_solana_dex_ids() -> list[str]:
    if _effective_supported_trading_solana_dex_ids is None:
        raise TradingConfigurationError(
            "Trading Solana dex configuration has not been applied — application startup validation must run first",
        )
    return list(_effective_supported_trading_solana_dex_ids)


def resolve_supported_trading_dex_identifiers() -> tuple[str, ...]:
    return tuple(resolve_supported_trading_solana_dex_ids())


def is_supported_trading_solana_dex_id(dex_id: str) -> bool:
    normalized_dex_id = dex_id.strip().lower()
    for supported_dex_id in resolve_supported_trading_solana_dex_ids():
        if supported_dex_id == normalized_dex_id:
            return True
    return False
