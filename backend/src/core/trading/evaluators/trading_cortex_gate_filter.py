from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_inference_provider import (
    get_trading_cortex_inference_service,
)
from src.core.trading.cortex.trading_cortex_request_builder import (
    TradingCortexRequestBuilder,
)
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexScoringBatchRequest,
    TradingCortexScoringResponse,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingSnapshot,
)
from src.core.trading.trading_structures import (
    TradingCandidate,
    TradingCortexInferenceSnapshot,
    TradingFilterVerdict,
)
from src.core.utils.log_utils import get_visual_width
from src.logging.logger import console_color_codes, get_application_logger

logger = get_application_logger(__name__)


def _cortex_holding_time_max_minutes() -> float:
    return settings.TRADING_CORTEX_HOLDING_TIME_MAX_HOURS * 60.0


def sort_trading_candidates_by_cortex_final_trade_score(candidates: list[TradingCandidate],descending: bool) -> list[TradingCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: candidate.cortex_diagnostics.inference_snapshot.final_trade_score,
        reverse=descending,
    )


def apply_trading_cortex_gate_filter(
        candidates: list[TradingCandidate],
        shadow_snapshot: TradingShadowingSnapshot,
        gate_enabled: bool,
) -> list[TradingCandidate]:
    request_builder = TradingCortexRequestBuilder()
    scoring_requests = []
    scoring_candidates: list[TradingCandidate] = []
    skipped_without_cortex: list[TradingCandidate] = []
    for candidate in candidates:
        try:
            scoring_requests.append(
                request_builder.build_trade_scoring_request(
                    candidate=candidate,
                    shadow_snapshot=shadow_snapshot,
                )
            )
            scoring_candidates.append(candidate)
        except ValueError as exc:
            log_method = logger.error if gate_enabled else logger.warning
            log_method(
                "[TRADING][PIPELINE][TRADING][CORTEX] Candidate %s is not cortex-ready: %s; %s",
                candidate.token.symbol,
                exc,
                "blocking execution" if gate_enabled else "retaining without cortex inference",
            )
            if gate_enabled:
                return []
            skipped_without_cortex.append(candidate)

    if not scoring_requests:
        if gate_enabled:
            return []
        return candidates

    scoring_batch_request = TradingCortexScoringBatchRequest(requests=scoring_requests)

    inference_service = get_trading_cortex_inference_service()
    scoring_batch_response = inference_service.score_trade_batch(scoring_batch_request)

    if not scoring_batch_response.responses:
        log_method = logger.error if gate_enabled else logger.warning
        log_method(
            "[TRADING][PIPELINE][TRADING][CORTEX] TradingCortex returned an empty scoring response for %d candidates; %s",
            len(candidates),
            "blocking execution" if gate_enabled else "continuing without cortex inference",
        )
        return [] if gate_enabled else candidates

    first_response = scoring_batch_response.responses[0]
    if not first_response.model_ready:
        logger.warning(
            "[TRADING][PIPELINE][TRADING][CORTEX] Cortex model is not ready; %s %d candidates",
            "blocking execution for" if gate_enabled else "continuing without cortex inference for",
            len(candidates),
        )
        return [] if gate_enabled else candidates

    logger.info(
        "[TRADING][PIPELINE][TRADING][CORTEX] Scored %d candidates model_version=%s feature_set=%s gate=%s",
        len(scoring_batch_response.responses),
        first_response.model_version,
        first_response.feature_set_version,
        "enabled" if gate_enabled else "disabled",
    )

    response_by_request_identifier = {
        scoring_response.request_identifier: scoring_response
        for scoring_response in scoring_batch_response.responses
        if scoring_response.request_identifier
    }

    retained: list[TradingCandidate] = []
    rejected: list[TradingCandidate] = []

    for scoring_request, candidate in zip(scoring_requests, scoring_candidates, strict=True):
        scoring_response = response_by_request_identifier.get(scoring_request.request_identifier)
        if scoring_response is None or not scoring_response.model_ready:
            log_method = logger.error if gate_enabled else logger.warning
            log_method(
                "[TRADING][PIPELINE][TRADING][CORTEX] Missing or not-ready cortex response for %s; %s candidate",
                scoring_request.request_identifier,
                "blocking" if gate_enabled else "retaining",
            )
            if gate_enabled:
                rejected.append(candidate)
            else:
                retained.append(candidate)
            continue

        gate_verdict = _evaluate_gate_verdict(scoring_response)
        candidate.cortex_diagnostics.inference_snapshot = _build_inference_snapshot(
            scoring_response=scoring_response,
            gate_verdict=gate_verdict,
        )

        if not gate_enabled or gate_verdict.is_accepted:
            retained.append(candidate)
        else:
            rejected.append(candidate)

    _log_cortex_evaluation_details(retained=retained, rejected=rejected)

    if rejected:
        logger.info(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Retained %d / %d candidates",
            len(retained),
            len(candidates),
        )
    else:
        logger.debug(
            "[TRADING][PIPELINE][TRADING][CORTEX][GATE] All %d candidates passed cortex gate",
            len(candidates),
        )

    return sort_trading_candidates_by_cortex_final_trade_score(retained, descending=True) + skipped_without_cortex


def _log_cortex_evaluation_details(
        retained: list[TradingCandidate],
        rejected: list[TradingCandidate],
) -> None:
    red: str = console_color_codes["RED"]
    green: str = console_color_codes["GREEN"]
    grey: str = console_color_codes["GREY"]
    reset: str = console_color_codes["RESET"]

    rejected_by_score_ascending = sort_trading_candidates_by_cortex_final_trade_score(rejected, descending=False)
    retained_by_score_ascending = sort_trading_candidates_by_cortex_final_trade_score(retained, descending=False)

    for candidate in rejected_by_score_ascending:
        snapshot = candidate.cortex_diagnostics.inference_snapshot
        if not snapshot:
            continue

        prefix: str = f"{candidate.token.symbol} {red}rejected{reset}"
        visual_length: int = get_visual_width(prefix)
        padding: str = " " * max(0, 45 - visual_length)

        metrics_table: str = _format_cortex_metrics_table(snapshot)
        logger.debug("[TRADING][PIPELINE][TRADING][CORTEX][GATE] %s%s Reasons: %s", prefix, padding, metrics_table)

    for candidate in retained_by_score_ascending:
        snapshot = candidate.cortex_diagnostics.inference_snapshot
        if not snapshot:
            continue

        prefix: str = f"{candidate.token.symbol} {green}retained{reset}"
        visual_length: int = get_visual_width(prefix)
        padding: str = " " * max(0, 45 - visual_length)

        metrics_table: str = _format_cortex_metrics_table(snapshot)
        logger.debug("[TRADING][PIPELINE][TRADING][CORTEX][GATE] %s%s Reasons: %s", prefix, padding, metrics_table)


def _format_cortex_metrics_table(snapshot: TradingCortexInferenceSnapshot) -> str:
    red: str = console_color_codes["RED"]
    grey: str = console_color_codes["GREY"]
    reset: str = console_color_codes["RESET"]

    score_str: str = f"{snapshot.final_trade_score:>6.2f}"

    wr_color: str = red if snapshot.success_probability < settings.TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD else grey
    wr_str: str = f"{snapshot.success_probability * 100:>5.1f}%"

    tox_color: str = red if snapshot.toxicity_probability > settings.TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD else grey
    tox_str: str = f"{snapshot.toxicity_probability * 100:>5.1f}%"

    pnl_color: str = red if snapshot.expected_profit_and_loss_percentage < settings.TRADING_CORTEX_PNL_THRESHOLD else grey
    pnl_str: str = f"{snapshot.expected_profit_and_loss_percentage:>7.2f}%"
    holding_value = snapshot.predicted_holding_time_minutes
    holding_color: str = red if holding_value > _cortex_holding_time_max_minutes() else grey
    holding_str: str = f"{holding_value:>6.1f}m"

    return (
        f"{grey}Score:{reset} {score_str} {grey}|{reset} "
        f"{grey}Win:{reset} {wr_color}{wr_str}{reset} {grey}|{reset} "
        f"{grey}Tox:{reset} {tox_color}{tox_str}{reset} {grey}|{reset} "
        f"{grey}PnL:{reset} {pnl_color}{pnl_str}{reset} {grey}|{reset} "
        f"{grey}Hold:{reset} {holding_color}{holding_str}{reset}"
    )


def _evaluate_gate_verdict(scoring_response: TradingCortexScoringResponse) -> TradingFilterVerdict:
    if (
            scoring_response.success_probability is None
            or scoring_response.toxicity_probability is None
            or scoring_response.expected_profit_and_loss_percentage is None
            or scoring_response.predicted_holding_time_minutes is None
    ):
        raise ValueError("Cannot evaluate cortex gate from incomplete scoring response")

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

    holding_time_max_minutes = _cortex_holding_time_max_minutes()
    if scoring_response.predicted_holding_time_minutes > holding_time_max_minutes:
        rejection_reasons.append(
            f"predicted_holding_time_minutes {scoring_response.predicted_holding_time_minutes:.1f} > {holding_time_max_minutes:.1f} ({settings.TRADING_CORTEX_HOLDING_TIME_MAX_HOURS:.1f}h)"
        )

    return TradingFilterVerdict(
        is_accepted=not rejection_reasons,
        rejection_reasons=rejection_reasons,
    )


def _build_inference_snapshot(
        scoring_response: TradingCortexScoringResponse,
        gate_verdict: TradingFilterVerdict,
) -> TradingCortexInferenceSnapshot:
    if (
            scoring_response.success_probability is None
            or scoring_response.toxicity_probability is None
            or scoring_response.expected_profit_and_loss_percentage is None
            or scoring_response.predicted_holding_time_minutes is None
            or scoring_response.final_trade_score is None
            or scoring_response.model_version is None
    ):
        raise ValueError("Cannot persist incomplete TradingCortexInferenceSnapshot")
    return TradingCortexInferenceSnapshot(
        success_probability=scoring_response.success_probability,
        toxicity_probability=scoring_response.toxicity_probability,
        expected_profit_and_loss_percentage=scoring_response.expected_profit_and_loss_percentage,
        predicted_holding_time_minutes=scoring_response.predicted_holding_time_minutes,
        final_trade_score=scoring_response.final_trade_score,
        model_version=scoring_response.model_version,
        model_ready=scoring_response.model_ready,
        gate_verdict=gate_verdict,
    )
