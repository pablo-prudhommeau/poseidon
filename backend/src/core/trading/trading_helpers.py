from __future__ import annotations

from src.core.structures.structures import Token
from src.core.trading.screener.trading_screener_structures import TradingScreenerEnvelope
from src.core.trading.trading_structures import (
    TradingCandidate,
    TradingCandidateAiAnalysis,
    TradingDexMarketSnapshot,
)


def build_trading_candidate(
        token: Token,
        market_snapshot: TradingDexMarketSnapshot,
        screener_envelope: TradingScreenerEnvelope,
) -> TradingCandidate:
    return TradingCandidate(
        token=token,
        market_snapshot=market_snapshot,
        screener_envelope=screener_envelope,
        quality_score=0.0,
        ai_analysis=TradingCandidateAiAnalysis(
            adjusted_quality_score=0.0,
            quality_delta=0.0,
            buy_probability=0.0,
        ),
    )
