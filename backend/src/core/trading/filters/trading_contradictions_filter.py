from __future__ import annotations

from typing import List, Optional

from src.core.trading.trading_structures import TradingCandidate, TradingFilterVerdict
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingContradictionsChecker:
    @staticmethod
    def _total_transactions(buys: Optional[int], sells: Optional[int]) -> Optional[int]:
        if buys is None or sells is None:
            return None
        return buys + sells

    @staticmethod
    def _transactions_from_token_information(token_information: DexscreenerTokenInformation, window: str) -> Optional[int]:
        if token_information.transactions is None:
            return None
        if window == "m5" and token_information.transactions.m5:
            return TradingContradictionsChecker._total_transactions(token_information.transactions.m5.buys, token_information.transactions.m5.sells)
        if window == "h1" and token_information.transactions.h1:
            return TradingContradictionsChecker._total_transactions(token_information.transactions.h1.buys, token_information.transactions.h1.sells)
        if window == "h6" and token_information.transactions.h6:
            return TradingContradictionsChecker._total_transactions(token_information.transactions.h6.buys, token_information.transactions.h6.sells)
        if window == "h24" and token_information.transactions.h24:
            return TradingContradictionsChecker._total_transactions(token_information.transactions.h24.buys, token_information.transactions.h24.sells)
        return None

    @staticmethod
    def _non_decreasing(sequence: List[Optional[int]]) -> bool:
        last: Optional[int] = None
        for value in sequence:
            if value is None:
                continue
            if last is not None and value < last:
                return False
            last = value
        return True

    def evaluate(self, candidate: TradingCandidate, token_information: Optional[DexscreenerTokenInformation]) -> TradingFilterVerdict:
        reasons: List[str] = []

        if token_information is not None:
            if token_information.fully_diluted_valuation is not None and token_information.market_cap is not None:
                if token_information.market_cap > token_information.fully_diluted_valuation * 1.05:
                    reasons.append("FDV_LT_MARKETCAP")

            if token_information.liquidity is not None and token_information.market_cap is not None:
                if token_information.liquidity.usd > token_information.market_cap:
                    reasons.append("LIQUIDITY_GT_MARKETCAP")

            volume_24h_usd: Optional[float] = token_information.volume.h24 if token_information.volume else None
            transactions_24h = self._transactions_from_token_information(token_information, "h24")
            if volume_24h_usd is not None and transactions_24h is not None:
                if (volume_24h_usd > 0.0 and transactions_24h == 0) or (volume_24h_usd == 0.0 and transactions_24h > 0):
                    reasons.append("VOLUME_TXNS_CONFLICT")

            transactions_5m = self._transactions_from_token_information(token_information, "m5")
            transactions_1h = self._transactions_from_token_information(token_information, "h1")
            transactions_6h = self._transactions_from_token_information(token_information, "h6")
            transactions_24h_count = self._transactions_from_token_information(token_information, "h24")
            if not self._non_decreasing([transactions_5m, transactions_1h, transactions_6h, transactions_24h_count]):
                reasons.append("TXNS_NON_MONOTONIC")

        return TradingFilterVerdict(is_accepted=(len(reasons) == 0), rejection_reasons=reasons)


def apply_contradictions_filter(
        candidates: list[TradingCandidate],
        token_price_information_list: list[DexscreenerTokenInformation],
) -> list[TradingCandidate]:
    from src.core.trading.analytics.trading_analytics_recorder import TradingAnalyticsRecorder

    checker = TradingContradictionsChecker()
    retained: list[TradingCandidate] = []

    for rank, candidate in enumerate(candidates, start=1):
        price_information = _find_token_information_for_candidate(token_price_information_list, candidate)
        verdict = checker.evaluate(candidate, price_information)

        if verdict.is_accepted:
            retained.append(candidate)
        else:
            reason = "CONTRAD:" + "|".join(verdict.rejection_reasons)
            logger.debug("[TRADING][FILTER][CONTRAD] %s — %s", candidate.token.symbol, reason)
            TradingAnalyticsRecorder.persist_and_broadcast_skip(candidate, rank, reason)

    if not retained:
        logger.info("[TRADING][FILTER][CONTRAD] Zero candidates after contradictions check")
    else:
        logger.info("[TRADING][FILTER][CONTRAD] Retained %d / %d candidates", len(retained), len(candidates))

    return retained


def _find_token_information_for_candidate(
        token_information_list: list[DexscreenerTokenInformation],
        candidate: TradingCandidate,
) -> Optional[DexscreenerTokenInformation]:
    preferred_pair: Optional[str] = candidate.pair_address if hasattr(candidate, "pair_address") else None
    for token_information in token_information_list:
        same_token = token_information.base_token.address == candidate.token.token_address
        if not same_token:
            continue
        if preferred_pair and token_information.pair_address == preferred_pair:
            return token_information
    for token_information in token_information_list:
        if token_information.base_token.address == candidate.dexscreener_token_information.base_token.address:
            return token_information
    return None
