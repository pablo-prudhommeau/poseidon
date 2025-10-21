from __future__ import annotations

from typing import List, Tuple

from src.configuration.config import settings
from src.core.gates.trending_scoring import ScoringEngine
from src.core.structures.structures import Candidate
from src.core.utils.trending_utils import preload_best_prices, recently_traded, _price_from
from src.integrations.dexscreener.dexscreener_structures import TokenPrice
from src.logging.logger import get_logger

log = get_logger(__name__)


class CandidateGatesStage:
    """
    Apply statistics scoring, cooldown, risk checks and price sanity.
    """

    def __init__(self) -> None:
        self.minimum_statistics_score: float = settings.SCORE_MIN_STATISTICS

    def preload_best_prices(self, candidates: List[Candidate]) -> List[TokenPrice]:
        return preload_best_prices(candidates)

    def apply_statistics_gate(self, candidates: List[Candidate]) -> Tuple[List[Candidate], ScoringEngine]:
        """Statistics scoring and filtering."""
        engine = ScoringEngine().fit(candidates)
        ready: List[Candidate] = []
        for candidate in candidates:
            stat_score = engine.stat_score(candidate)
            candidate.statistics_score = stat_score
            if stat_score >= self.minimum_statistics_score:
                ready.append(candidate)
            else:
                log.debug("[TREND][GATE][STAT] %s — stat=%.2f < %.2f", candidate.symbol, stat_score,
                          self.minimum_statistics_score)
        if not ready:
            log.info("[TREND][GATE][STAT] 0 candidates after gate #2.")
        return ready, engine

    def apply_risk_and_price_gates(self, candidates: List[Candidate], token_prices: List[TokenPrice]) -> List[Candidate]:
        """Cooldown, risk manager, and price sanity checks."""
        from src.core.gates.risk_manager import AdaptiveRiskManager

        cooldown_minutes = int(settings.DEXSCREENER_REBUY_COOLDOWN_MIN)
        max_price_deviation = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)
        risk_manager = AdaptiveRiskManager()

        eligible: List[Candidate] = []
        for candidate in sorted(candidates, key=lambda x: x.statistics_score, reverse=True):
            if candidate.token_address and recently_traded(candidate.token_address, minutes=cooldown_minutes):
                log.debug("[TREND][GATE][COOLDOWN] %s", candidate.symbol)
                from src.core.jobs.trending.execution_stage import AnalyticsRecorder
                AnalyticsRecorder.persist_and_broadcast_skip(candidate, len(eligible) + 1, "COOLDOWN")
                continue

            pre_decision = risk_manager.pre_entry_decision(candidate)
            if not pre_decision.should_buy:
                log.debug("[TREND][GATE][RISK] %s — %s", candidate.symbol, pre_decision.reason)
                from src.core.jobs.trending.execution_stage import AnalyticsRecorder
                AnalyticsRecorder.persist_and_broadcast_skip(candidate, len(eligible) + 1,
                                                             f"RISK:{pre_decision.reason}")
                continue

            dex_price = _price_from(token_prices, candidate)
            if dex_price is None or dex_price <= 0.0:
                log.debug("[TREND][GATE][PRICE] Invalid DEX price for %s", candidate.symbol)
                from src.core.jobs.trending.execution_stage import AnalyticsRecorder
                AnalyticsRecorder.persist_and_broadcast_skip(candidate, len(eligible) + 1, "NO_DEX_PRICE")
                continue

            quoted_price = float(candidate.price_usd)
            if dex_price and quoted_price:
                low, high = sorted([dex_price, quoted_price])
                if low > 0.0 and (high / low) > max_price_deviation:
                    log.debug("[TREND][GATE][DEVIATION] %s dex=%.10f quote=%.10f", candidate.symbol, dex_price,
                              quoted_price)
                    from src.core.jobs.trending.execution_stage import AnalyticsRecorder
                    AnalyticsRecorder.persist_and_broadcast_skip(candidate, len(eligible) + 1, "PRICE_DEVIATION")
                    continue

            candidate.dex_price = float(dex_price)
            eligible.append(candidate)

        if not eligible:
            log.info("[TREND][GATE] 0 candidates after risk/price checks.")
        return eligible
