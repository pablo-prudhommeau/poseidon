from __future__ import annotations

from typing import List

from src.core.trading.trading_structures import TradingCandidate, TradingFilterVerdict
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingContradictionsChecker:
    @staticmethod
    def _non_decreasing(sequence: List[int]) -> bool:
        last: int | None = None
        for value in sequence:
            if last is not None and value < last:
                return False
            last = value
        return True

    def evaluate(self, candidate: TradingCandidate) -> TradingFilterVerdict:
        market_snapshot = candidate.market_snapshot
        reasons: List[str] = []

        if market_snapshot.market_cap_usd > market_snapshot.fully_diluted_valuation_usd * 1.05:
            reasons.append("FDV_LT_MARKETCAP")

        if market_snapshot.liquidity_usd > market_snapshot.market_cap_usd:
            reasons.append("LIQUIDITY_GT_MARKETCAP")

        transactions_24h = market_snapshot.transaction_count_h24
        if (
                (market_snapshot.volume_h24_usd > 0.0 and transactions_24h == 0)
                or (market_snapshot.volume_h24_usd == 0.0 and transactions_24h > 0)
        ):
            reasons.append("VOLUME_TXNS_CONFLICT")

        if not self._non_decreasing([
            market_snapshot.transaction_count_m5,
            market_snapshot.transaction_count_h1,
            market_snapshot.transaction_count_h6,
            market_snapshot.transaction_count_h24,
        ]):
            reasons.append("TXNS_NON_MONOTONIC")

        return TradingFilterVerdict(is_accepted=(len(reasons) == 0), rejection_reasons=reasons)


def apply_contradictions_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    from src.core.trading.trading_service import record_skipped_trading_evaluation

    checker = TradingContradictionsChecker()
    retained: list[TradingCandidate] = []

    for rank, candidate in enumerate(candidates, start=1):
        verdict = checker.evaluate(candidate)

        if verdict.is_accepted:
            retained.append(candidate)
        else:
            reason = "CONTRAD:" + "|".join(verdict.rejection_reasons)
            logger.debug("[TRADING][FILTER][CONTRAD] %s — %s", candidate.token.symbol, reason)
            record_skipped_trading_evaluation(candidate, rank, reason)

    if not retained:
        logger.info("[TRADING][FILTER][CONTRAD] Zero candidates after contradictions check")
    else:
        logger.info("[TRADING][FILTER][CONTRAD] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
