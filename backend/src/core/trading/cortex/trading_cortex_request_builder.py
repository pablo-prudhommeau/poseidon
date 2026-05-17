from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexCandidateFeatureSnapshot,
    TradingCortexShadowMetricFeatureSnapshot,
    TradingCortexShadowRegimeFeatureSnapshot,
    TradingCortexScoringRequest,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingIntelligenceMetric,
    TradingShadowingIntelligenceSnapshot,
)
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation


class TradingCortexRequestBuilder:
    def build_trade_scoring_request(
            self,
            candidate: TradingCandidate,
            candidate_rank: int,
            shadow_snapshot: Optional[TradingShadowingIntelligenceSnapshot],
    ) -> TradingCortexScoringRequest:
        token_information = candidate.dexscreener_token_information
        request_identifier = self.build_request_identifier(candidate, candidate_rank)
        return TradingCortexScoringRequest(
            request_identifier=request_identifier,
            feature_set_version=settings.TRADING_CORTEX_FEATURE_SET_VERSION,
            candidate_features=self._build_candidate_feature_snapshot(candidate, candidate_rank, token_information),
            shadow_regime_features=self._build_shadow_regime_feature_snapshot(shadow_snapshot),
            shadow_metric_features=self._build_shadow_metric_feature_snapshots(candidate),
        )

    def build_request_identifier(self, candidate: TradingCandidate, candidate_rank: int) -> str:
        pair_address = candidate.dexscreener_token_information.pair_address
        return f"rank-{candidate_rank}:{candidate.token.symbol}:{pair_address}"

    def _build_candidate_feature_snapshot(
            self,
            candidate: TradingCandidate,
            candidate_rank: int,
            token_information: DexscreenerTokenInformation,
    ) -> TradingCortexCandidateFeatureSnapshot:
        volume = token_information.volume
        liquidity = token_information.liquidity
        price_change = token_information.price_change
        transactions = token_information.transactions
        blockchain_network = candidate.token.chain.value if candidate.token.chain is not None else None
        order_notional_value_usd = self._estimate_order_notional_value_usd(candidate)

        return TradingCortexCandidateFeatureSnapshot(
            token_symbol=candidate.token.symbol,
            blockchain_network=blockchain_network,
            dex_identifier=token_information.dex_id,
            pair_address=token_information.pair_address,
            candidate_rank=candidate_rank,
            quality_score=candidate.quality_score,
            token_age_hours=token_information.age_hours,
            liquidity_usd=liquidity.usd if liquidity is not None and liquidity.usd is not None else 0.0,
            market_cap_usd=token_information.market_cap,
            fully_diluted_valuation_usd=token_information.fully_diluted_valuation,
            dexscreener_boost=token_information.boost,
            volume_5m_usd=volume.m5 if volume is not None and volume.m5 is not None else 0.0,
            volume_1h_usd=volume.h1 if volume is not None and volume.h1 is not None else 0.0,
            volume_6h_usd=volume.h6 if volume is not None and volume.h6 is not None else 0.0,
            volume_24h_usd=volume.h24 if volume is not None and volume.h24 is not None else 0.0,
            price_change_percentage_5m=price_change.m5 if price_change is not None and price_change.m5 is not None else 0.0,
            price_change_percentage_1h=price_change.h1 if price_change is not None and price_change.h1 is not None else 0.0,
            price_change_percentage_6h=price_change.h6 if price_change is not None and price_change.h6 is not None else 0.0,
            price_change_percentage_24h=price_change.h24 if price_change is not None and price_change.h24 is not None else 0.0,
            transaction_count_5m=float(transactions.m5.total_transactions) if transactions is not None and transactions.m5 is not None else 0.0,
            transaction_count_1h=float(transactions.h1.total_transactions) if transactions is not None and transactions.h1 is not None else 0.0,
            transaction_count_6h=float(transactions.h6.total_transactions) if transactions is not None and transactions.h6 is not None else 0.0,
            transaction_count_24h=float(transactions.h24.total_transactions) if transactions is not None and transactions.h24 is not None else 0.0,
            buy_to_sell_ratio=self._compute_buy_to_sell_ratio(token_information),
            order_notional_value_usd=order_notional_value_usd,
        )

    def _estimate_order_notional_value_usd(self, candidate: TradingCandidate) -> Optional[float]:
        if not settings.TRADING_SHADOWING_ENABLED:
            return None
        return settings.TRADING_SHADOWING_FIXED_NOTIONAL_USD * candidate.shadow_notional_multiplier

    def _compute_buy_to_sell_ratio(self, token_information: DexscreenerTokenInformation) -> float:
        transactions = token_information.transactions
        if transactions is None:
            return 0.5
        reference_bucket = transactions.h1 if transactions.h1 is not None else transactions.h24
        if reference_bucket is None:
            return 0.5
        total_transaction_count = reference_bucket.buys + reference_bucket.sells
        if total_transaction_count <= 0:
            return 0.5
        return reference_bucket.buys / total_transaction_count

    def _build_shadow_regime_feature_snapshot(
            self,
            shadow_snapshot: Optional[TradingShadowingIntelligenceSnapshot],
    ) -> Optional[TradingCortexShadowRegimeFeatureSnapshot]:
        if shadow_snapshot is None:
            return None
        return TradingCortexShadowRegimeFeatureSnapshot(
            meta_win_rate=shadow_snapshot.summary.meta_win_rate,
            meta_average_profit_and_loss_percentage=shadow_snapshot.summary.meta_average_pnl,
            meta_average_holding_time_hours=shadow_snapshot.summary.meta_average_holding_time_hours,
            meta_expected_pnl_velocity=shadow_snapshot.summary.meta_expected_pnl_velocity,
            meta_profit_factor=shadow_snapshot.summary.meta_profit_factor,
            meta_expected_value_usd=shadow_snapshot.summary.meta_expected_value_usd,
            chronicle_profit_factor=shadow_snapshot.summary.chronicle_profit_factor,
            sparse_expected_value_usd=shadow_snapshot.summary.sparse_expected_value_usd,
        )

    def _build_shadow_metric_feature_snapshots(
            self,
            candidate: TradingCandidate,
    ) -> list[TradingCortexShadowMetricFeatureSnapshot]:
        intelligence_snapshot = candidate.shadow_diagnostics.intelligence_snapshot
        if intelligence_snapshot is None:
            return []
        return [
            self._build_shadow_metric_feature_snapshot(evaluated_metric)
            for evaluated_metric in intelligence_snapshot.metrics
            if evaluated_metric.candidate_value is not None
        ]

    def _build_shadow_metric_feature_snapshot(
            self,
            evaluated_metric: TradingShadowingIntelligenceMetric,
    ) -> TradingCortexShadowMetricFeatureSnapshot:
        return TradingCortexShadowMetricFeatureSnapshot(
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
