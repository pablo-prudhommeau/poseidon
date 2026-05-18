from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.evaluators.trading_age_filter import apply_age_filter
from src.core.trading.evaluators.trading_ai_scorer import apply_ai_scorer
from src.core.trading.evaluators.trading_contradictions_filter import apply_contradictions_filter
from src.core.trading.evaluators.trading_cooldown_filter import apply_cooldown_filter
from src.core.trading.evaluators.trading_cortex_gate_filter import apply_trading_cortex_gate_filter
from src.core.trading.evaluators.trading_deduplication_filter import apply_deduplication_filter
from src.core.trading.evaluators.trading_fundamentals_filter import apply_fundamentals_filter
from src.core.trading.evaluators.trading_liquidity_filter import apply_liquidity_filter
from src.core.trading.evaluators.trading_momentum_filter import apply_momentum_filter
from src.core.trading.evaluators.trading_price_deviation_filter import apply_price_deviation_filter
from src.core.trading.evaluators.trading_quality_scorer import compute_quality_scores, apply_quality_gate
from src.core.trading.evaluators.trading_risk_filter import apply_risk_filter
from src.core.trading.evaluators.trading_shadowing_notional_booster import apply_shadowing_notional_boost
from src.core.trading.evaluators.trading_shadowing_toxic_exposure_filter import apply_shadowing_toxic_exposure_filter
from src.core.trading.evaluators.trading_volume_filter import apply_volume_filter
from src.core.trading.execution.trading_executor import TradingExecutor
from src.core.trading.execution.trading_order_builder import build_route_for_live_execution
from src.core.trading.shadowing.cache.trading_shadowing_cache import trading_shadowing_cache
from src.core.trading.shadowing.trading_shadowing_snapshot_service import evaluate_candidate_shadowing
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingSnapshot,
    TradingShadowingPhase,
)
from src.core.trading.trading_service import fetch_trading_candidates_sync, record_skipped_trading_evaluation, record_trading_evaluation
from src.core.trading.trading_structures import TradingCandidate, TradingOrderPayload, TradingPipelineContext
from src.core.trading.trading_utils import (
    preload_best_prices,
)
from src.core.utils.format_utils import tail
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingPipeline:
    def __init__(self) -> None:
        self._executor = TradingExecutor()

    def run_once(self) -> None:
        logger.info("[TRADING][PIPELINE] Starting new trading cycle")
        try:
            self._execute_pipeline()
        except RuntimeError as exception:
            if "interpreter shutdown" in str(exception):
                logger.warning("[TRADING][PIPELINE] Pipeline cycle aborted due to application shutdown")
            else:
                logger.exception("[TRADING][PIPELINE] Pipeline cycle failed — %s", exception)
        except Exception as exception:
            logger.exception("[TRADING][PIPELINE] Pipeline cycle failed — %s", exception)
        logger.info("[TRADING][PIPELINE] Trading cycle complete")

    def _execute_pipeline(self) -> None:
        pipeline_context = TradingPipelineContext()

        candidates = self._step_fetch_candidates()
        if not candidates:
            return

        candidates = self._step_filter_allowed_chains(candidates)
        if not candidates:
            return

        candidates = self._step_filter_supported_dexes(candidates)
        if not candidates:
            return

        candidates = self._step_deduplication(candidates)
        if not candidates:
            return

        shadow_snapshot: TradingShadowingSnapshot | None = None
        shadow_gate_enabled = (
                settings.TRADING_GATE_SHADOWING_TOXIC_METRICS_ENABLED
                or settings.TRADING_GATE_SHADOWING_PERFORMANCE_ENABLED
        )
        cortex_gate_required = self._is_cortex_gate_required()
        shadow_snapshot_required = (
                settings.TRADING_SHADOWING_ENABLED
                or settings.TRADING_CORTEX_ENABLED
                or shadow_gate_enabled
                or cortex_gate_required
        )
        if not settings.TRADING_GATE_SHADOWING_TOXIC_METRICS_ENABLED:
            logger.debug("[TRADING][PIPELINE][GATE][SHADOWING_TOXIC] Shadowing toxic metrics gate is disabled")
        if not settings.TRADING_GATE_SHADOWING_PERFORMANCE_ENABLED:
            logger.debug("[TRADING][PIPELINE][GATE][SHADOWING_PERFORMANCE] Shadowing performance gate is disabled")
        if not settings.TRADING_GATE_CORTEX_ENABLED:
            logger.debug("[TRADING][PIPELINE][GATE][CORTEX] Cortex gate is disabled")
        if not settings.TRADING_GATE_FUNDAMENTALS_ENABLED:
            logger.debug("[TRADING][PIPELINE][GATE][FUNDAMENTALS] Fundamentals gate is disabled")

        if shadow_snapshot_required:
            shadow_snapshot = self._step_load_shadowing_snapshot()
            if shadow_snapshot is None:
                if shadow_gate_enabled or cortex_gate_required:
                    logger.warning(
                        "[TRADING][PIPELINE][SHADOWING] Shadowing snapshot not yet in cache — "
                        "at least one enabled gate requires it; aborting trading cycle"
                    )
                    return
                logger.warning(
                    "[TRADING][PIPELINE][SHADOWING] Shadowing snapshot not yet in cache — "
                    "continuing without shadow/cortex evaluation snapshots"
                )
            else:
                pipeline_context.shadowing_snapshot = shadow_snapshot

        if shadow_gate_enabled:
            if shadow_snapshot is None:
                logger.warning("[TRADING][PIPELINE][GATE] Shadow gate enabled but snapshot is missing; aborting trading cycle")
                return
            if shadow_snapshot.regime.phase != TradingShadowingPhase.TRADABLE:
                logger.info("[TRADING][PIPELINE][GATE] Shadowing snapshot in %s phase — live trading is paused until sufficient data is collected.", shadow_snapshot.regime.phase.value)
                return
            if settings.TRADING_GATE_SHADOWING_PERFORMANCE_ENABLED and not self._is_shadow_performance_gate_satisfied(shadow_snapshot):
                return

        shadow_snapshot_active = (
                shadow_snapshot is not None
                and shadow_snapshot.regime.phase == TradingShadowingPhase.TRADABLE
        )

        if settings.TRADING_GATE_FUNDAMENTALS_ENABLED:
            candidates = self._step_filter_volume(candidates)
            if not candidates:
                return

            candidates = self._step_filter_liquidity(candidates)
            if not candidates:
                return

            candidates = self._step_filter_fundamentals(candidates)
            if not candidates:
                return

            candidates = self._step_filter_momentum(candidates)
            if not candidates:
                return

            candidates = self._step_filter_age(candidates)
            if not candidates:
                return

        self._step_compute_quality_scores(candidates)

        if settings.TRADING_GATE_FUNDAMENTALS_ENABLED:
            candidates = self._step_apply_quality_gate(candidates)
            if not candidates:
                return

        shadow_evaluation_active = (
                settings.TRADING_SHADOWING_ENABLED
                and shadow_snapshot_active
        )

        if shadow_evaluation_active:
            self._step_evaluate_shadowing(candidates, shadow_snapshot)

        token_price_information_list = preload_best_prices(candidates)
        pipeline_context.token_price_information_list = token_price_information_list

        candidates = self._step_contradictions(candidates, token_price_information_list)
        if not candidates:
            return

        if settings.TRADING_GATE_FUNDAMENTALS_ENABLED:
            candidates = self._step_risk_filter(candidates)
            if not candidates:
                return

            candidates = self._step_cooldown(candidates)
            if not candidates:
                return

            candidates = self._step_price_deviation(candidates, token_price_information_list)
            if not candidates:
                return

            candidates = self._step_ai_scorer(candidates, pipeline_context)
            if not candidates:
                return

        if settings.TRADING_GATE_SHADOWING_TOXIC_METRICS_ENABLED:
            candidates = self._step_shadowing_toxic_exposure_filter(candidates, shadow_snapshot)
            if not candidates:
                return

        if shadow_gate_enabled and shadow_snapshot_active:
            self._step_shadowing_notional_boost(candidates, shadow_snapshot)

        if settings.TRADING_GATE_CORTEX_ENABLED:
            if shadow_snapshot is None:
                logger.warning(
                    "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Shadowing snapshot is missing; "
                    "blocking execution for %d candidates",
                    len(candidates),
                )
                return
            if shadow_snapshot.regime.phase != TradingShadowingPhase.TRADABLE:
                logger.warning(
                    "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Shadowing snapshot phase is %s; "
                    "blocking execution because cortex gate requires an active snapshot",
                    shadow_snapshot.regime.phase.value,
                )
                return
            if not self._is_cortex_gate_activation_ready(shadow_snapshot):
                logger.warning(
                    "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Cortex gate activation requires %d eligible outcomes, got %d; blocking execution for %d candidates",
                    settings.TRADING_CORTEX_MIN_ELIGIBLE_OUTCOMES_FOR_TRAINING,
                    shadow_snapshot.regime.cortex_training_eligible_outcome_count,
                    len(candidates),
                )
                return
            if all(candidate.trading_cortex_inference_snapshot is not None for candidate in candidates):
                candidates = self._step_apply_existing_cortex_gate_snapshots(candidates)
            else:
                candidates = self._step_apply_trading_cortex_gate(candidates, shadow_snapshot, True)
            if not candidates:
                return

        self._step_execute(candidates, pipeline_context)

    def _step_fetch_candidates(self) -> list[TradingCandidate]:
        candidates = fetch_trading_candidates_sync()
        logger.info("[TRADING][PIPELINE][FETCH] Fetched %d raw candidates", len(candidates))
        if candidates:
            symbols = [candidate.token.symbol for candidate in candidates]
            logger.debug("[TRADING][PIPELINE][FETCH] Candidates: %s", ", ".join(symbols))
        return candidates

    def _step_filter_allowed_chains(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        allowed_chains = set(settings.TRADING_ALLOWED_CHAINS)
        if not settings.PAPER_MODE:
            allowed_chains = {BlockchainNetwork.SOLANA.value}
            logger.info(
                "[TRADING][PIPELINE][CHAIN_FILTER] Live execution guard active: restricting candidate universe to %s",
                BlockchainNetwork.SOLANA.value,
            )
        retained: list[TradingCandidate] = []
        rejected_counts: dict[str, int] = {}
        rejected_examples: dict[str, list[str]] = {}
        for candidate in candidates:
            chain_identifier = candidate.token.chain.value if candidate.token.chain else ""
            if chain_identifier in allowed_chains:
                retained.append(candidate)
            else:
                rejected_counts[chain_identifier] = rejected_counts.get(chain_identifier, 0) + 1
                examples = rejected_examples.setdefault(chain_identifier, [])
                if len(examples) < 5:
                    examples.append(candidate.token.symbol)

        if rejected_counts:
            chains_summary = ", ".join([f"{chain}({count})" for chain, count in sorted(rejected_counts.items())])
            examples_summary = "; ".join([f"{chain}:[{', '.join(examples)}]" for chain, examples in rejected_examples.items()])
            logger.debug("[TRADING][PIPELINE][CHAIN_FILTER] Rejected chains summary: %s — examples: %s", chains_summary, examples_summary)

        if len(retained) < len(candidates):
            logger.info(
                "[TRADING][PIPELINE][CHAIN_FILTER] Retained %d / %d candidates (allowed chains: %s)",
                len(retained), len(candidates), ", ".join(sorted(allowed_chains)),
            )
        return retained

    def _step_filter_supported_dexes(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        allowed_solana_dexes = set(settings.TRADING_SOLANA_SUPPORTED_DEX_IDS)
        retained: list[TradingCandidate] = []
        rejected_counts: dict[str, int] = {}
        rejected_examples: dict[str, list[str]] = {}
        for candidate in candidates:
            chain_identifier = candidate.token.chain.value if candidate.token.chain else ""
            dex_identifier = (candidate.dexscreener_token_information.dex_id or "").strip().lower()

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
            logger.debug("[TRADING][PIPELINE][DEX_FILTER] Rejected dexes summary: %s — examples: %s", dex_summary, examples_summary)

        if len(retained) < len(candidates):
            logger.info(
                "[TRADING][PIPELINE][DEX_FILTER] Retained %d / %d candidates (filtered by DEX)",
                len(retained), len(candidates),
            )
        return retained

    def _step_filter_volume(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_volume_filter(candidates)

    def _step_filter_liquidity(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_liquidity_filter(candidates)

    def _step_filter_fundamentals(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_fundamentals_filter(candidates)

    def _step_filter_momentum(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_momentum_filter(candidates)

    def _step_filter_age(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_age_filter(candidates)

    def _step_compute_quality_scores(self, candidates: list[TradingCandidate]) -> None:
        compute_quality_scores(candidates)

    def _step_apply_quality_gate(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_quality_gate(candidates)

    def _step_deduplication(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_deduplication_filter(candidates)

    def _step_contradictions(self, candidates: list[TradingCandidate], token_price_information_list: list) -> list[TradingCandidate]:
        return apply_contradictions_filter(candidates, token_price_information_list)

    def _step_risk_filter(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_risk_filter(candidates)

    def _step_cooldown(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_cooldown_filter(candidates)

    def _step_price_deviation(self, candidates: list[TradingCandidate], token_price_information_list: list) -> list[TradingCandidate]:
        return apply_price_deviation_filter(candidates, token_price_information_list)

    def _step_ai_scorer(self, candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> list[TradingCandidate]:
        return apply_ai_scorer(candidates, pipeline_context)

    def _step_load_shadowing_snapshot(self):
        snapshot = trading_shadowing_cache.get_shadowing_snapshot()
        if snapshot is None:
            return None
        logger.info(
            "[TRADING][PIPELINE][SHADOWING] Shadowing snapshot loaded — phase=%s, outcomes=%d",
            snapshot.regime.phase.value, snapshot.regime.shadowing_resolved_outcome_count,
        )
        return snapshot

    def _is_shadow_performance_gate_satisfied(self, shadow_snapshot: TradingShadowingSnapshot) -> bool:
        chronicle_profit_factor = shadow_snapshot.regime.shadowing_performance_chronicle_profit_factor
        chronicle_threshold = shadow_snapshot.regime.shadowing_performance_chronicle_profit_factor_threshold
        if chronicle_profit_factor < chronicle_threshold:
            logger.warning(
                "[TRADING][PIPELINE][GATE][SHADOWING_SMA_PF] Chronicle profit factor %.2f is below %.2f; trading cycle blocked",
                chronicle_profit_factor,
                chronicle_threshold,
            )
            return False

        sparse_expected_value_usd = shadow_snapshot.regime.shadowing_performance_sparse_expected_value_usd
        sparse_expected_value_threshold = shadow_snapshot.regime.shadowing_performance_sparse_expected_value_usd_threshold
        if sparse_expected_value_usd < sparse_expected_value_threshold:
            logger.warning(
                "[TRADING][PIPELINE][GATE][SHADOWING_SPARSE_EV] Sparse expected value USD %.2f is below %.2f; trading cycle blocked",
                sparse_expected_value_usd,
                sparse_expected_value_threshold,
            )
            return False

        return True

    def _step_shadowing_toxic_exposure_filter(self, candidates: list[TradingCandidate], shadow_snapshot) -> list[TradingCandidate]:
        return apply_shadowing_toxic_exposure_filter(candidates, shadow_snapshot)

    def _step_shadowing_notional_boost(self, candidates: list[TradingCandidate], shadow_snapshot) -> None:
        apply_shadowing_notional_boost(candidates, shadow_snapshot)

    def _step_evaluate_shadowing(
            self,
            candidates: list[TradingCandidate],
            shadow_snapshot: TradingShadowingSnapshot,
    ) -> None:
        for candidate in candidates:
            candidate.shadowing_diagnostics = evaluate_candidate_shadowing(candidate, shadow_snapshot)

    def _step_apply_trading_cortex_gate(
            self,
            candidates: list[TradingCandidate],
            shadow_snapshot: TradingShadowingSnapshot,
            gate_enabled: bool,
    ) -> list[TradingCandidate]:
        return apply_trading_cortex_gate_filter(candidates, shadow_snapshot, gate_enabled)

    def _is_cortex_gate_required(self) -> bool:
        return settings.TRADING_GATE_CORTEX_ENABLED or settings.TRADING_CORTEX_ENABLED

    def _is_cortex_gate_activation_ready(self, shadow_snapshot: TradingShadowingSnapshot) -> bool:
        return (
                shadow_snapshot.regime.cortex_training_eligible_outcome_count
                >= settings.TRADING_CORTEX_MIN_ELIGIBLE_OUTCOMES_FOR_TRAINING
        )

    def _step_apply_existing_cortex_gate_snapshots(
            self,
            candidates: list[TradingCandidate],
    ) -> list[TradingCandidate]:
        retained: list[TradingCandidate] = []
        rejected: list[TradingCandidate] = []
        for candidate in candidates:
            cortex_inference_snapshot = candidate.trading_cortex_inference_snapshot
            if (
                    cortex_inference_snapshot is not None
                    and cortex_inference_snapshot.model_ready
                    and cortex_inference_snapshot.gate_verdict.is_accepted
            ):
                retained.append(candidate)
            else:
                rejected.append(candidate)

        if rejected:
            logger.info(
                "[TRADING][PIPELINE][TRADING][CORTEX][GATE] Retained %d / %d candidates from existing cortex snapshots",
                len(retained),
                len(candidates),
            )
        else:
            logger.debug(
                "[TRADING][PIPELINE][TRADING][CORTEX][GATE] All %d candidates passed from existing cortex snapshots",
                len(candidates),
            )
        return retained

    def _step_execute(self, candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> None:
        from sqlalchemy import select, func
        from src.persistence.database_session_manager import get_database_session
        from src.persistence.models import TradingPosition, PositionPhase
        from src.persistence.dao.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao

        with get_database_session() as database_session:
            current_open_count = database_session.execute(
                select(func.count(TradingPosition.id))
                .where(TradingPosition.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]))
            ).scalar_one_or_none() or 0

            portfolio_dao = TradingPortfolioSnapshotDao(database_session)
            latest_snapshot = portfolio_dao.retrieve_latest_snapshot()
            if not latest_snapshot:
                logger.info("[TRADING][PIPELINE][EXECUTE] No trading portfolio snapshot found")
                for rank, candidate in enumerate(candidates, start=1):
                    record_skipped_trading_evaluation(candidate, rank, "NO_PORTFOLIO_SNAPSHOT")
                return
            else:
                total_equity_usd = latest_snapshot.total_equity_value

        from src.core.trading.cache.trading_cache import trading_cache
        available_cash_usd = trading_cache.get_available_cash_usd()
        if available_cash_usd is None:
            logger.warning(
                "[TRADING][PIPELINE][EXECUTE] Available cash not yet in cache — cache not yet warmed up; skipping execution cycle"
            )
            for rank, candidate in enumerate(candidates, start=1):
                record_skipped_trading_evaluation(candidate, rank, "CACHE_NOT_READY")
            return
        per_buy_fraction = settings.TRADING_PER_BUY_FRACTION
        min_free_cash = settings.TRADING_MIN_FREE_CASH_USD
        max_positions = settings.TRADING_MAX_OPEN_POSITIONS

        if available_cash_usd < min_free_cash:
            logger.info("[TRADING][PIPELINE][EXECUTE] Insufficient free cash: %.2f < %.2f", available_cash_usd, min_free_cash)
            for rank, candidate in enumerate(candidates, start=1):
                record_skipped_trading_evaluation(candidate, rank, "NO_CASH")
            return

        executed_count = 0
        max_positions_logged = False

        for rank, candidate in enumerate(candidates, start=1):
            if current_open_count >= max_positions:
                if not max_positions_logged:
                    logger.info("[TRADING][PIPELINE][EXECUTE] Max positions limit reached (%d/%d) — skipping remaining", current_open_count, max_positions)
                    max_positions_logged = True
                record_skipped_trading_evaluation(candidate, rank, "MAX_POSITIONS")
                continue

            if available_cash_usd < min_free_cash:
                record_skipped_trading_evaluation(candidate, rank, "NO_CASH")
                continue

            available_to_spend = max(0.0, available_cash_usd - min_free_cash)
            order_notional = total_equity_usd * per_buy_fraction * candidate.shadow_notional_multiplier

            if order_notional > available_to_spend:
                logger.warning(
                    "[TRADING][PIPELINE][EXECUTE] Cap notional to respect min cash buffer: %.2f -> %.2f for %s",
                    order_notional, available_to_spend, candidate.token.symbol
                )
                order_notional = available_to_spend

            if order_notional <= 0:
                record_skipped_trading_evaluation(candidate, rank, "NO_CASH")
                continue
            dex_price = candidate.dex_price or candidate.dexscreener_token_information.price_usd or 0.0

            execution_route = build_route_for_live_execution(candidate, order_notional)

            free_cash_before = available_cash_usd
            free_cash_after = available_cash_usd - order_notional

            evaluation_id = record_trading_evaluation(
                candidate,
                rank=rank,
                decision="BUY",
                reason="EXECUTION",
                sizing_multiplier=candidate.shadow_notional_multiplier,
                order_notional_usd=order_notional,
                free_cash_before_usd=free_cash_before,
                free_cash_after_usd=free_cash_after,
            )

            order_payload = TradingOrderPayload(
                target_token=candidate.token,
                execution_price=dex_price,
                order_notional=order_notional,
                original_candidate=candidate,
                origin_evaluation_id=evaluation_id,
                execution_route=execution_route,
            )

            logger.info(
                "[TRADING][PIPELINE][EXECUTE] BUY #%d %s (%s) — notional=%.2f quality=%.2f shadow_mult=%.2f route=%s",
                rank, candidate.token.symbol, tail(candidate.token.token_address), order_notional, candidate.ai_adjusted_quality_score, candidate.shadow_notional_multiplier,
                "available" if execution_route is not None else "paper",
            )

            buy_succeeded = self._executor.buy(order_payload)

            if buy_succeeded:
                available_cash_usd = free_cash_after
                executed_count += 1
                current_open_count += 1
            else:
                logger.warning("[TRADING][PIPELINE][EXECUTE] BUY #%d %s failed — free cash unchanged", rank, candidate.token.symbol)

        logger.info("[TRADING][PIPELINE][EXECUTE] Executed %d buys this cycle", executed_count)





