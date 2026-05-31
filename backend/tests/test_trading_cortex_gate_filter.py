from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.cortex.trading_cortex_final_score_service import TradingCortexFinalScoreService
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexFeatureVectorSnapshot,
    TradingCortexNamedFeatureValue,
    TradingCortexPrediction,
)
from src.core.trading.evaluators.trading_cortex_gate_filter import (
    _evaluate_gate_verdict,
    sort_trading_candidates_by_cortex_final_trade_score,
)
from src.core.trading.screener.trading_screener_structures import TradingScreenerEnvelope
from src.core.trading.trading_structures import (
    TradingCandidate,
    TradingCandidateCortexDiagnostics,
    TradingCortexInferenceSnapshot,
    TradingDexMarketSnapshot,
    TradingFilterVerdict,
)
from src.core.trading.cortex.trading_cortex_structures import TradingCortexScoringResponse


def _build_market_snapshot() -> TradingDexMarketSnapshot:
    return TradingDexMarketSnapshot(
        price_usd=1.0,
        price_native=1.0,
        token_age_hours=2.0,
        volume_m5_usd=10000.0,
        volume_h1_usd=10000.0,
        volume_h6_usd=10000.0,
        volume_h24_usd=10000.0,
        liquidity_usd=10000.0,
        price_change_percentage_m5=1.0,
        price_change_percentage_h1=1.0,
        price_change_percentage_h6=1.0,
        price_change_percentage_h24=1.0,
        transaction_count_m5=10,
        transaction_count_h1=10,
        transaction_count_h6=10,
        transaction_count_h24=10,
        buy_to_sell_ratio=1.0,
        market_cap_usd=100000.0,
        fully_diluted_valuation_usd=100000.0,
    )


def _build_candidate(symbol: str, final_trade_score: float) -> TradingCandidate:
    inference_snapshot = TradingCortexInferenceSnapshot(
        success_probability=0.6,
        toxicity_probability=0.4,
        expected_profit_and_loss_percentage=1.0,
        predicted_holding_time_minutes=120.0,
        final_trade_score=final_trade_score,
        model_version="test_v1",
        model_ready=True,
        gate_verdict=TradingFilterVerdict(is_accepted=True, rejection_reasons=[]),
    )
    return TradingCandidate(
        token=Token(
            symbol=symbol,
            chain=BlockchainNetwork.SOLANA,
            token_address=f"{symbol}_token",
            pair_address=f"{symbol}_pair",
            dex_id="raydium",
        ),
        market_snapshot=_build_market_snapshot(),
        screener_envelope=TradingScreenerEnvelope(provider_id="test"),
        cortex_diagnostics=TradingCandidateCortexDiagnostics(inference_snapshot=inference_snapshot),
    )


def test_sort_trading_candidates_by_cortex_final_trade_score_descending() -> None:
    candidates = [
        _build_candidate("LOW", 40.0),
        _build_candidate("HIGH", 70.0),
        _build_candidate("MID", 55.0),
    ]

    ordered = sort_trading_candidates_by_cortex_final_trade_score(candidates, descending=True)

    assert [candidate.token.symbol for candidate in ordered] == ["HIGH", "MID", "LOW"]


def test_gate_rejects_predicted_holding_time_above_max_hours() -> None:
    scoring_response = TradingCortexScoringResponse(
        request_identifier="req-1",
        token_symbol="GENNY",
        feature_set_version="cortex_v1",
        model_version="test_v1",
        model_ready=True,
        success_probability=0.75,
        toxicity_probability=0.02,
        expected_profit_and_loss_percentage=3.6,
        predicted_holding_time_minutes=1208.9,
        final_trade_score=65.26,
        feature_count=1,
        golden_metric_count=0,
        toxic_metric_count=0,
    )

    gate_verdict = _evaluate_gate_verdict(scoring_response)

    assert gate_verdict.is_accepted is False
    assert any("predicted_holding_time_minutes" in reason for reason in gate_verdict.rejection_reasons)


def _build_feature_vector_snapshot() -> TradingCortexFeatureVectorSnapshot:
    return TradingCortexFeatureVectorSnapshot(
        feature_set_version="cortex_v1",
        named_feature_values=[TradingCortexNamedFeatureValue(feature_name="quality_score", feature_value=50.0)],
        metric_count=1,
        golden_metric_count=0,
        toxic_metric_count=0,
        golden_metric_ratio=0.0,
        toxic_metric_ratio=0.0,
        regime_signal=0.0,
    )


def test_final_trade_score_prefers_shorter_predicted_holding_time() -> None:
    final_score_service = TradingCortexFinalScoreService()
    feature_vector_snapshot = _build_feature_vector_snapshot()
    neutral_prediction_fields = {
        "success_probability": 0.55,
        "toxicity_probability": 0.45,
        "expected_profit_and_loss_percentage": 1.0,
        "used_model_names": [],
    }

    short_hold_score = final_score_service.calculate_final_score(
        prediction=TradingCortexPrediction(
            predicted_holding_time_minutes=60.0,
            **neutral_prediction_fields,
        ),
        feature_vector_snapshot=feature_vector_snapshot,
    ).final_trade_score
    long_hold_score = final_score_service.calculate_final_score(
        prediction=TradingCortexPrediction(
            predicted_holding_time_minutes=900.0,
            **neutral_prediction_fields,
        ),
        feature_vector_snapshot=feature_vector_snapshot,
    ).final_trade_score

    assert short_hold_score > long_hold_score
