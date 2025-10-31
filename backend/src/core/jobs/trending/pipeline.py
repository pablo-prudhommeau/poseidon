from __future__ import annotations

from src.core.jobs.trending.execution_stage import AiExecutionStage
from src.core.jobs.trending.gates_stage import CandidateGatesStage
from src.core.jobs.trending.selection_stage import CandidateSelectionStage

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


class TrendingPipeline:
    """
    Orchestrates the full trending evaluation and execution pipeline.
    """

    def __init__(self) -> None:
        self.selection_stage = CandidateSelectionStage()
        self.gates_stage = CandidateGatesStage()
        self.execution_stage = AiExecutionStage()

    def run_once(self) -> None:
        """Execute one full trending evaluation cycle."""
        if not settings.TREND_ENABLE:
            log.info("[TREND][RUN] disabled.")
            return

        # 1) Collect and pre-filter candidates
        raw_rows = self.selection_stage.fetch_candidates_raw()
        if not raw_rows:
            return

        strictly_kept_rows = self.selection_stage.apply_hard_filters(raw_rows)
        soft_filled_rows = self.selection_stage.apply_soft_fill(raw_rows, strictly_kept_rows)

        quality_ready_rows = self.selection_stage.apply_quality_gate(soft_filled_rows)
        if not quality_ready_rows:
            return

        candidates = self.selection_stage.order_and_truncate(quality_ready_rows)

        pruned_candidates = self.selection_stage.deduplicate_open_positions(candidates)
        if not pruned_candidates:
            return

        # 2) Preload prices once, then run the contradictions gate (pre-trade semantic sanity)
        token_prices = self.gates_stage.preload_best_prices(pruned_candidates)

        # NEW: semantic contradictions gate (FDV/Mcap, Liquidity/Mcap, Volume↔Txns, monotonicity)
        contradiction_clean: list = self.gates_stage.apply_contradictions_gate(pruned_candidates, token_prices)
        if not contradiction_clean:
            return

        # 3) Score + risk/price gates + AI execution
        statistics_ready, engine = self.gates_stage.apply_statistics_gate(contradiction_clean)
        if not statistics_ready:
            return

        eligible_candidates = self.gates_stage.apply_risk_and_price_gates(statistics_ready, token_prices)
        if not eligible_candidates:
            return

        self.execution_stage.ai_gate_and_execute(eligible_candidates, engine)

    def run(self) -> None:
        """Public entry-point to run one cycle. Kept for backwards compatibility."""
        self.run_once()
