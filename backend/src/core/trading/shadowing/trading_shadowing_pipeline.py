from __future__ import annotations

from datetime import datetime, timedelta

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_chain_capability_service import (
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_dex_capability_service import resolve_supported_trading_solana_dex_ids
from src.core.trading.analytics.trading_analytics_helpers import MINIMUM_POINTS_PER_BUCKET
from src.core.trading.cortex.trading_cortex_inference_provider import get_trading_cortex_inference_service
from src.core.trading.cortex.trading_cortex_request_builder import TradingCortexRequestBuilder
from src.core.trading.cortex.trading_cortex_structures import TradingCortexScoringBatchRequest
from src.core.trading.evaluators.trading_quality_scorer import compute_quality_score
from src.core.trading.shadowing.cache.trading_shadowing_cache import trading_shadowing_cache
from src.core.trading.shadowing.trading_shadowing_probe_helpers import build_trading_shadowing_probe_with_verdict
from src.core.trading.shadowing.trading_shadowing_snapshot_service import (
    evaluate_candidate_shadowing,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingPhase,
    TradingShadowingSnapshot,
)
from src.core.trading.trading_service import fetch_trading_candidates_sync
from src.core.trading.trading_structures import TradingCandidate, TradingCortexInferenceSnapshot, TradingFilterVerdict
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)


class TradingShadowingPipeline:
    def __init__(self) -> None:
        pass

    def run_once(self) -> None:
        if not settings.TRADING_SHADOWING_ENABLED:
            logger.debug("[TRADING][SHADOWING][PIPELINE] Shadowing tracking is disabled, skipping")
            return

        logger.info("[TRADING][SHADOWING][PIPELINE] Starting shadowing tracking cycle")
        try:
            self._execute_shadowing_pipeline()
        except Exception as exception:
            logger.exception("[TRADING][SHADOWING][PIPELINE] Shadowing tracking cycle failed — %s", exception)
        logger.info("[TRADING][SHADOWING][PIPELINE] Shadowing tracking cycle complete")

    def _execute_shadowing_pipeline(self) -> None:
        if settings.TRADING_SHADOWING_MIN_ELIGIBLE_OUTCOMES_FOR_SHADOWING < MINIMUM_POINTS_PER_BUCKET:
            raise ValueError(
                f"Configuration paradox: TRADING_SHADOWING_MIN_ELIGIBLE_OUTCOMES_FOR_SHADOWING ({settings.TRADING_SHADOWING_MIN_ELIGIBLE_OUTCOMES_FOR_SHADOWING}) "
                f"cannot be lower than the statistical engine constraint MINIMUM_POINTS_PER_BUCKET ({MINIMUM_POINTS_PER_BUCKET})"
            )

        candidates = fetch_trading_candidates_sync()
        if not candidates:
            logger.info("[TRADING][SHADOWING][PIPELINE] No candidates fetched")
            return

        candidates = self._filter_allowed_chains(candidates)
        if not candidates:
            return

        candidates = self._filter_supported_dexes(candidates)
        if not candidates:
            return

        current_time = get_current_local_datetime()

        fixed_notional = settings.TRADING_SHADOWING_FIXED_NOTIONAL_USD
        cooldown_minutes = settings.TRADING_SHADOWING_TOKEN_COOLDOWN_MINUTES
        shadow_probe_count = 0
        cooldown_skip_count = 0

        cooldown_threshold = current_time - timedelta(minutes=cooldown_minutes)
        token_addresses = [candidate.token.token_address for candidate in candidates]

        with get_database_session() as database_session:
            probe_dao = TradingShadowingProbeDao(database_session)
            recent_probes = probe_dao.retrieve_recent_probes_by_tokens(token_addresses, cooldown_threshold)
            cooldown_addresses = {probe.token_address for probe in recent_probes}

        admissible_candidates = []
        for rank, candidate in enumerate(candidates, start=1):
            token_address = candidate.token.token_address
            if token_address in cooldown_addresses:
                cooldown_skip_count += 1
                continue

            quality_score = compute_quality_score(candidate)
            candidate.quality_score = quality_score
            candidate.ai_analysis.adjusted_quality_score = quality_score

            entry_price = candidate.market_snapshot.price_usd
            admissible_candidates.append((rank, candidate, entry_price))

        cached_snapshot = trading_shadowing_cache.get_shadowing_snapshot()
        if cached_snapshot is None:
            logger.info("[TRADING][SHADOWING][PIPELINE] Shadowing snapshot missing from cache, triggering background rebuild and skipping cycle")
            cache_invalidator.mark_dirty(CacheRealm.SHADOWING_SNAPSHOT)
            return

        current_phase = cached_snapshot.regime.phase
        shadow_can_simulate = len(cached_snapshot.metric_profiles) > 0

        if current_phase == TradingShadowingPhase.TRADABLE and not shadow_can_simulate:
            logger.info("[TRADING][SHADOWING][PIPELINE] Shadowing phase is TRADABLE but metric profiles are not yet ready, skipping cycle")
            return

        if current_phase == TradingShadowingPhase.DISABLED:
            logger.debug("[TRADING][SHADOWING][PIPELINE] Shadowing phase is DISABLED, skipping")
            return

        if shadow_can_simulate:
            for rank, candidate, _ in admissible_candidates:
                candidate.shadowing_diagnostics = evaluate_candidate_shadowing(candidate, cached_snapshot)

        if settings.TRADING_CORTEX_ENABLED and admissible_candidates and shadow_can_simulate:
            request_builder = TradingCortexRequestBuilder()
            trade_scoring_requests = []
            cortex_scoring_candidates: list[tuple[int, TradingCandidate]] = []
            for rank, candidate, _ in admissible_candidates:
                try:
                    trade_scoring_requests.append(
                        request_builder.build_trade_scoring_request(
                            candidate=candidate,
                            shadow_snapshot=cached_snapshot,
                        )
                    )
                    cortex_scoring_candidates.append((rank, candidate))
                except ValueError as exc:
                    logger.debug(
                        "[TRADING][SHADOWING][PIPELINE][CORTEX] Skipping cortex for %s: %s",
                        candidate.token.symbol,
                        exc,
                    )
            if trade_scoring_requests:
                scoring_batch_request = TradingCortexScoringBatchRequest(requests=trade_scoring_requests)
                try:
                    inference_service = get_trading_cortex_inference_service()
                    scoring_batch_response = inference_service.score_trade_batch(scoring_batch_request)
                    response_by_request_identifier = {
                        scoring_response.request_identifier: scoring_response
                        for scoring_response in scoring_batch_response.responses
                        if scoring_response.request_identifier
                    }
                    for rank, candidate in cortex_scoring_candidates:
                        request_identifier = request_builder.build_request_identifier(candidate)
                        scoring_response = response_by_request_identifier.get(request_identifier)
                        if (
                                scoring_response
                                and scoring_response.model_ready
                                and scoring_response.model_version is not None
                                and scoring_response.success_probability is not None
                                and scoring_response.toxicity_probability is not None
                                and scoring_response.expected_profit_and_loss_percentage is not None
                                and scoring_response.predicted_holding_time_minutes is not None
                                and scoring_response.final_trade_score is not None
                        ):
                            candidate.cortex_diagnostics.inference_snapshot = TradingCortexInferenceSnapshot(
                                success_probability=scoring_response.success_probability,
                                toxicity_probability=scoring_response.toxicity_probability,
                                expected_profit_and_loss_percentage=scoring_response.expected_profit_and_loss_percentage,
                                predicted_holding_time_minutes=scoring_response.predicted_holding_time_minutes,
                                final_trade_score=scoring_response.final_trade_score,
                                model_version=scoring_response.model_version,
                                model_ready=scoring_response.model_ready,
                                gate_verdict=TradingFilterVerdict(is_accepted=True, rejection_reasons=[]),
                            )
                except Exception as exc:
                    logger.exception("[TRADING][SHADOWING][PIPELINE] TradingCortex inference failed for probes: %s", exc)

        for rank, candidate, entry_price in admissible_candidates:
            tp1_price = entry_price * (1.0 + settings.TRADING_TP1_EXIT_FRACTION)
            tp2_price = entry_price * (1.0 + settings.TRADING_TP2_EXIT_FRACTION)
            stop_loss_price = entry_price * (1.0 - settings.TRADING_STOP_LOSS_FRACTION)

            if self._persist_shadow_probe(
                    candidate=candidate,
                    rank=rank,
                    notional=fixed_notional,
                    tp1_price=tp1_price,
                    tp2_price=tp2_price,
                    stop_loss_price=stop_loss_price,
                    current_time=current_time,
                    shadow_can_simulate=shadow_can_simulate,
                    cached_snapshot=cached_snapshot,
            ):
                cooldown_addresses.add(candidate.token.token_address)
                shadow_probe_count += 1

        logger.info(
            "[TRADING][SHADOWING][PIPELINE] Recorded %d shadowing probes from %d candidates (%d skipped by cooldown)",
            shadow_probe_count, len(candidates), cooldown_skip_count,
        )

    def _filter_allowed_chains(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        allowed_chains = {
            blockchain_network.value
            for blockchain_network in resolve_trading_allowed_blockchain_networks()
        }
        retained = [
            candidate for candidate in candidates
            if candidate.token.chain.value in allowed_chains
        ]
        if len(retained) < len(candidates):
            logger.debug("[TRADING][SHADOWING][PIPELINE] Chain filter retained %d / %d", len(retained), len(candidates))
        return retained

    def _filter_supported_dexes(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        allowed_solana_dexes = set(resolve_supported_trading_solana_dex_ids())
        retained: list[TradingCandidate] = []
        rejected_counts: dict[str, int] = {}
        rejected_examples: dict[str, list[str]] = {}
        for candidate in candidates:
            chain_identifier = candidate.token.chain.value if candidate.token.chain else ""
            dex_identifier = (candidate.token.dex_id or "").strip().lower()

            if chain_identifier == BlockchainNetwork.SOLANA.value:
                if dex_identifier in allowed_solana_dexes:
                    retained.append(candidate)
                else:
                    rejected_counts[dex_identifier] = rejected_counts.get(dex_identifier, 0) + 1
                    examples = rejected_examples.setdefault(dex_identifier, [])
                    if len(examples) < 5:
                        examples.append(candidate.token.symbol)
            else:
                retained.append(candidate)

        if rejected_counts:
            dex_summary = ", ".join([f"{dex}({count})" for dex, count in sorted(rejected_counts.items())])
            examples_summary = "; ".join([f"{dex}:[{', '.join(examples)}]" for dex, examples in rejected_examples.items()])
            logger.debug(
                "[TRADING][SHADOWING][PIPELINE][DEX_FILTER] Rejected dexes summary: %s — examples: %s",
                dex_summary,
                examples_summary,
            )

        if len(retained) < len(candidates):
            logger.info(
                "[TRADING][SHADOWING][PIPELINE][DEX_FILTER] Retained %d / %d candidates (allowed dexes: %s)",
                len(retained),
                len(candidates),
                ", ".join(sorted(allowed_solana_dexes)),
            )
        return retained

    def _persist_shadow_probe(
            self,
            candidate: TradingCandidate,
            rank: int,
            notional: float,
            tp1_price: float,
            tp2_price: float,
            stop_loss_price: float,
            current_time: datetime,
            shadow_can_simulate: bool,
            cached_snapshot: TradingShadowingSnapshot,
    ) -> bool:
        probe = build_trading_shadowing_probe_with_verdict(
            candidate=candidate,
            rank=rank,
            notional=notional,
            current_time=current_time,
            shadow_can_simulate=shadow_can_simulate,
            shadowing_regime=cached_snapshot.regime if shadow_can_simulate else None,
            take_profit_tier_1_price=tp1_price,
            take_profit_tier_2_price=tp2_price,
            stop_loss_price=stop_loss_price,
        )

        entry_price_usd = candidate.market_snapshot.price_usd
        token_symbol = candidate.token.symbol

        with get_database_session() as database_session:
            probe_dao = TradingShadowingProbeDao(database_session)
            probe_dao.save(probe)

        logger.debug(
            "[TRADING][SHADOWING][PERSIST] Recorded shadowing probe for %s at price %.10f",
            token_symbol,
            entry_price_usd,
        )
        return True
