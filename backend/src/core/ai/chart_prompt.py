from __future__ import annotations

from typing import Dict, Any


def build_chartist_system_prompt() -> str:
    """
    System prompt: the model must act as a short-term crypto chart analyst.
    """
    return (
        "You are a meticulous crypto chart analyst specialized in very short term trading on volatile tokens.\n"
        "You analyze a single candlestick chart image and output ONLY structured JSON matching the provided schema.\n"
        "Time horizons are intraday (minutes to hours). Avoid hindsight bias; assess continuation vs pullback risk.\n"
        "Be conservative when evidence is weak."
    )


def build_chartist_user_prompt(
        *,
        symbol: str | None,
        chain_name: str | None,
        pair_address: str | None,
        timeframe_minutes: int,
        lookback_minutes: int,
) -> str:
    """
    User prompt: context about the asset and time frame.
    """
    label = symbol or f"{chain_name}:{pair_address}"
    return (
        f"Asset: {label}\n"
        f"Timeframe: {timeframe_minutes} minutes per candle\n"
        f"Lookback: last {lookback_minutes} minutes\n"
        "Task: detect actionable short-term patterns and return probabilities:\n"
        "- tp1_probability: probability that TP1 is reached BEFORE any stop loss within the next 30–60 minutes.\n"
        "- sl_before_tp_probability: probability that a typical stop loss is hit BEFORE TP1 in the same horizon.\n"
        "- trend_state: one of ['uptrend','downtrend','range','transition'].\n"
        "- momentum_bias: one of ['bullish','bearish','neutral'].\n"
        "- patterns: up to 3 pattern objects {name, confidence, direction}.\n"
        "- quality_score_delta: a signed float in [-20, +20] to adjust baseline quality score.\n"
        "Calibration: stay inside bounds; if evidence is mixed, keep probabilities near 0.50 and delta near 0.\n"
        "Return JSON only; no markdown, no prose."
    )


def chartist_json_schema() -> Dict[str, Any]:
    """
    JSON Schema used with Structured Outputs to enforce shape and types.
    """
    return {
        "name": "chart_ai_signal",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tp1_probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "sl_before_tp_probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "trend_state": {"type": "string", "enum": ["uptrend", "downtrend", "range", "transition"]},
                "momentum_bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                "quality_score_delta": {"type": "number", "minimum": -20.0, "maximum": 20.0},
                "patterns": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "direction": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                        },
                        "required": ["name", "direction", "confidence"]
                    }
                }
            },
            "required": ["tp1_probability", "sl_before_tp_probability", "trend_state", "momentum_bias", "quality_score_delta", "patterns"]
        },
        "strict": True
    }
