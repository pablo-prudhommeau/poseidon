from __future__ import annotations

from typing import Protocol

from src.core.trading.trading_structures import TradingCandidate


class ScreenerProvider(Protocol):
    @property
    def provider_id(self) -> str:
        ...

    def fetch_trending_candidates(self) -> list[TradingCandidate]:
        ...

    def refresh_candidates(self, candidates: list[TradingCandidate]) -> None:
        ...


_default_screener_provider: ScreenerProvider | None = None


def get_trading_screener_provider() -> ScreenerProvider:
    global _default_screener_provider
    if _default_screener_provider is None:
        from src.integrations.dexscreener.dexscreener_screener_provider import DexscreenerScreenerProvider

        _default_screener_provider = DexscreenerScreenerProvider()
    return _default_screener_provider
