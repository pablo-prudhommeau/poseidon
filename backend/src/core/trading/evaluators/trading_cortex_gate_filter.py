from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_inference_provider import get_trading_cortex_inference_service
from src.core.trading.cortex.trading_cortex_request_builder import TradingCortexRequestBuilder
from src.core.trading.cortex.trading_cortex_structures import TradingCortexScoringBatchRequest, TradingCortexScoringResponse
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingIntelligenceSnapshot,
    TradingShadowingPhase,
)
from src.core.trading.trading_structures import TradingCandidate, TradingCortexInferenceSnapshot, TradingFilterVerdict
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_trading_cortex_gate_filter(
        candidates: list[TradingCandidate],
        shadow_snapshot: Optional[TradingShadowingIntelligenceSnapshot],
) -> list[TradingCandidate]:
    if not settings.TRADING_GATE_CORTEX_ENABLED:
        logger.debug("[TRADING][PIPELINE][TRADING][CORTEX][GATE] TradingCortex gate is disabled")
        return candidates
    if not candidates:
        logger.debug("[TRADING][PIPELINE][TRADING][CORTEX][GATE] No candidates available for cortex gate")
        return candidates

    if shadow_snapshot is None:
        logger.info("[TRADING][PIPELINE][TRADING][CORTEX][GATE] Shadow intelligence snapshot is missing; bypassing cortex gate")
        return candidates

    if shadow_snapshot.summary.phase != TradingShadowingPhase.ACTIVE:
        logger.info(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Shadow intelligence phase is %s; bypassing cortex gate",
            shadow_snapshot.summary.phase.value,
        )
        return candidates

    request_builder = TradingCortexRequestBuilder()
    scoring_requests = [
        request_builder.build_trade_scoring_request(
            candidate=candidate,
            candidate_rank=candidate_rank,
            shadow_snapshot=shadow_snapshot,
        )
        for candidate_rank, candidate in enumerate(candidates, start=1)
    ]
    scoring_batch_request = TradingCortexScoringBatchRequest(requests=scoring_requests)

    try:
        inference_service = get_trading_cortex_inference_service()
        scoring_batch_response = inference_service.score_trade_batch(scoring_batch_request)
    except Exception as exc:
        logger.exception(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] TradingCortex inference failed for %d candidates; blocking execution: %s",
            len(candidates),
            exc,
        )
        return []

    if not scoring_batch_response.responses:
        logger.error(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] TradingCortex returned an empty scoring response for %d candidates; blocking execution",
            len(candidates),
        )
        return []

    first_response = scoring_batch_response.responses[0]
    if not first_response.model_ready:
        logger.error(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Cortex model is not ready; blocking execution for %d candidates",
            len(candidates),
        )
        return []

    logger.info(
        "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Scored %d candidates model_version=%s feature_set=%s",
        len(scoring_batch_response.responses),
        first_response.model_version,
        first_response.feature_set_version,
    )

    response_by_request_identifier = {
        scoring_response.request_identifier: scoring_response
        for scoring_response in scoring_batch_response.responses
        if scoring_response.request_identifier
    }

    retained: list[TradingCandidate] = []
    rejected: list[TradingCandidate] = []

    for scoring_request, candidate in zip(scoring_requests, candidates, strict=True):
        scoring_response = response_by_request_identifier.get(scoring_request.request_identifier)
        if scoring_response is None or not scoring_response.model_ready:
            logger.error(
                "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Missing or not-ready cortex response for %s; blocking candidate",
                scoring_request.request_identifier,
            )
            rejected.append(candidate)
            continue

        gate_verdict = _evaluate_gate_verdict(scoring_response)
        candidate.trading_cortex_inference_snapshot = _build_inference_snapshot(
            scoring_response=scoring_response,
            gate_verdict=gate_verdict,
        )

        if gate_verdict.is_accepted:
            retained.append(candidate)
            logger.info(
                "[TRADING][PIPELINE][TRADING][CORTEX][GATE] RETAINED %s | Score: %.2f | Win: %.1f%% | Tox: %.1f%% | PnL: %.1f%%\033[0m",
                candidate.token.symbol,
                scoring_response.final_trade_score,
                scoring_response.success_probability * 100,
                scoring_response.toxicity_probability * 100,
                scoring_response.expected_profit_and_loss_percentage,
            )
            continue

        rejected.append(candidate)
        logger.debug(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Rejected %s: %s",
            candidate.token.symbol,
            ", ".join(gate_verdict.rejection_reasons),
        )

    if rejected:
        logger.info(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Rejected %d/%d candidates",
            len(rejected),
            len(candidates),
        )

    return retained


def _evaluate_gate_verdict(scoring_response: TradingCortexScoringResponse) -> TradingFilterVerdict:
    rejection_reasons: list[str] = []

    if scoring_response.success_probability < settings.TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD:
        rejection_reasons.append(
            f"success_probability {scoring_response.success_probability:.3f} < {settings.TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD:.3f}"
        )

    if scoring_response.toxicity_probability > settings.TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD:
        rejection_reasons.append(
            f"toxicity_probability {scoring_response.toxicity_probability:.3f} > {settings.TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD:.3f}"
        )

    if scoring_response.expected_profit_and_loss_percentage < settings.TRADING_CORTEX_PNL_THRESHOLD:
        rejection_reasons.append(
            f"expected_profit_and_loss_percentage {scoring_response.expected_profit_and_loss_percentage:.2f} < {settings.TRADING_CORTEX_PNL_THRESHOLD:.2f}"
        )

    return TradingFilterVerdict(
        is_accepted=not rejection_reasons,
        rejection_reasons=rejection_reasons,
    )


def _build_inference_snapshot(
        scoring_response: TradingCortexScoringResponse,
        gate_verdict: TradingFilterVerdict,
) -> TradingCortexInferenceSnapshot:
    return TradingCortexInferenceSnapshot(
        success_probability=scoring_response.success_probability,
        toxicity_probability=scoring_response.toxicity_probability,
        expected_profit_and_loss_percentage=scoring_response.expected_profit_and_loss_percentage,
        final_trade_score=scoring_response.final_trade_score,
        model_version=scoring_response.model_version,
        model_ready=scoring_response.model_ready,
        gate_verdict=gate_verdict,
    )
