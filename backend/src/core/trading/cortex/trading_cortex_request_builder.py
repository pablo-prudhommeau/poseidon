from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexCandidateFeatureSnapshot,
    TradingCortexShadowingMetricFeatureSnapshot,
    TradingCortexShadowingRegimeFeatureSnapshot,
    TradingCortexScoringRequest,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingCandidateShadowingMetricEvaluation,
    TradingShadowingSnapshot,
)
from src.core.trading.trading_structures import TradingCandidate


class TradingCortexRequestBuilder:
    def build_trade_scoring_request(
            self,
            candidate: TradingCandidate,
            shadow_snapshot: TradingShadowingSnapshot,
    ) -> TradingCortexScoringRequest:
        self._assert_cortex_ready(candidate, shadow_snapshot)
        request_identifier = self.build_request_identifier(candidate)
        return TradingCortexScoringRequest(
            request_identifier=request_identifier,
            feature_set_version=settings.TRADING_CORTEX_FEATURE_SET_VERSION,
            candidate_features=self._build_candidate_feature_snapshot(candidate),
            regime_features=self._build_regime_feature_snapshot(shadow_snapshot),
            metric_features=self._build_metric_feature_snapshots(candidate),
        )

    def build_request_identifier(self, candidate: TradingCandidate) -> str:
        return f"{candidate.token.symbol}:{candidate.token.pair_address}"

    def _assert_cortex_ready(
            self,
            candidate: TradingCandidate,
            shadow_snapshot: TradingShadowingSnapshot,
    ) -> None:
        if not shadow_snapshot.metric_profiles:
            raise ValueError(
                "TradingShadowingSnapshot.metric_profiles must be non-empty before cortex scoring"
            )
        evaluated_metrics = candidate.shadowing_diagnostics.evaluated_metrics
        if not evaluated_metrics:
            raise ValueError(
                f"Candidate {candidate.token.symbol} has no shadowing metric evaluations; "
                "evaluate shadowing before cortex scoring"
            )

    def _build_candidate_feature_snapshot(
            self,
            candidate: TradingCandidate,
    ) -> TradingCortexCandidateFeatureSnapshot:
        market_snapshot = candidate.market_snapshot
        blockchain_network = candidate.token.chain.value if candidate.token.chain is not None else None

        return TradingCortexCandidateFeatureSnapshot(
            token_symbol=candidate.token.symbol,
            blockchain_network=blockchain_network,
            dex_identifier=candidate.token.dex_id,
            pair_address=candidate.token.pair_address,
            quality_score=candidate.quality_score,
            token_age_hours=market_snapshot.token_age_hours,
            liquidity_usd=market_snapshot.liquidity_usd,
            market_cap_usd=market_snapshot.market_cap_usd,
            fully_diluted_valuation_usd=market_snapshot.fully_diluted_valuation_usd,
            promotion_score=market_snapshot.promotion_score,
            volume_5m_usd=market_snapshot.volume_m5_usd,
            volume_1h_usd=market_snapshot.volume_h1_usd,
            volume_6h_usd=market_snapshot.volume_h6_usd,
            volume_24h_usd=market_snapshot.volume_h24_usd,
            price_change_percentage_5m=market_snapshot.price_change_percentage_m5,
            price_change_percentage_1h=market_snapshot.price_change_percentage_h1,
            price_change_percentage_6h=market_snapshot.price_change_percentage_h6,
            price_change_percentage_24h=market_snapshot.price_change_percentage_h24,
            transaction_count_5m=float(market_snapshot.transaction_count_m5),
            transaction_count_1h=float(market_snapshot.transaction_count_h1),
            transaction_count_6h=float(market_snapshot.transaction_count_h6),
            transaction_count_24h=float(market_snapshot.transaction_count_h24),
            buy_to_sell_ratio=market_snapshot.buy_to_sell_ratio,
        )

    def _build_regime_feature_snapshot(
            self,
            shadow_snapshot: TradingShadowingSnapshot,
    ) -> TradingCortexShadowingRegimeFeatureSnapshot:
        return TradingCortexShadowingRegimeFeatureSnapshot(
            metrics_meta_win_rate=shadow_snapshot.regime.metrics_meta_win_rate,
            metrics_meta_average_pnl=shadow_snapshot.regime.metrics_meta_average_pnl,
            metrics_meta_average_holding_time_hours=shadow_snapshot.regime.metrics_meta_average_holding_time_hours,
            metrics_meta_expected_pnl_velocity=shadow_snapshot.regime.metrics_meta_expected_pnl_velocity,
            metrics_meta_profit_factor=shadow_snapshot.regime.metrics_meta_profit_factor,
            metrics_meta_expected_value_usd=shadow_snapshot.regime.metrics_meta_expected_value_usd,
            edge_chronicle_profit_factor=shadow_snapshot.regime.edge_chronicle_profit_factor,
            edge_sparse_expected_value_usd=shadow_snapshot.regime.edge_sparse_expected_value_usd,
        )

    def _build_metric_feature_snapshots(
            self,
            candidate: TradingCandidate,
    ) -> list[TradingCortexShadowingMetricFeatureSnapshot]:
        evaluated_metrics = candidate.shadowing_diagnostics.evaluated_metrics
        metric_feature_snapshots: list[TradingCortexShadowingMetricFeatureSnapshot] = []
        for evaluated_metric in evaluated_metrics:
            if evaluated_metric.candidate_value is None:
                raise ValueError(
                    f"Metric {evaluated_metric.metric_key} for {candidate.token.symbol} "
                    "has no candidate_value after shadowing evaluation"
                )
            metric_feature_snapshots.append(self._build_metric_feature_snapshot(evaluated_metric))
        return metric_feature_snapshots

    def _build_metric_feature_snapshot(
            self,
            evaluated_metric: TradingCandidateShadowingMetricEvaluation,
    ) -> TradingCortexShadowingMetricFeatureSnapshot:
        return TradingCortexShadowingMetricFeatureSnapshot(
            metric_key=evaluated_metric.metric_key,
            candidate_value=evaluated_metric.candidate_value,
            bucket_index=evaluated_metric.bucket_index,
            bucket_win_rate=evaluated_metric.bucket_win_rate,
            bucket_average_profit_and_loss_percentage=evaluated_metric.bucket_average_pnl,
            bucket_average_holding_time_hours=evaluated_metric.bucket_average_holding_time / 60.0,
            bucket_expected_pnl_velocity=evaluated_metric.bucket_expected_pnl_velocity,
            bucket_outlier_hit_rate=evaluated_metric.bucket_outlier_hit_rate,
            bucket_sample_count=evaluated_metric.bucket_sample_count,
            is_toxic=evaluated_metric.is_toxic,
            is_golden=evaluated_metric.is_golden,
            normalized_influence=evaluated_metric.normalized_influence,
        )
