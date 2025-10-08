from __future__ import annotations

import base64
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from src.configuration.config import settings
from src.core.ai.chart_prompt import build_chartist_system_prompt, build_chartist_user_prompt, chartist_json_schema
from src.logging.logger import get_logger

log = get_logger(__name__)


def _is_gpt5_family(model_name: str) -> bool:
    """Return True if the model is in the GPT-5 family (e.g., gpt-5, gpt-5-mini)."""
    name = (model_name or "").lower()
    return name.startswith("gpt-5")


def _build_common_kwargs(
        *,
        model_name: str,
        messages: list[dict],
        response_format: dict,
) -> dict:
    """
    Build request kwargs compatible with both GPT-5 and non-GPT-5 models.
    - GPT-5 family: do NOT send temperature/top_p (unsupported).
    - Others: honor optional settings.CHART_AI_TEMPERATURE if provided.
    - Seed is added when configured (helps reproducibility where supported).
    """
    kwargs: dict = {
        "model": model_name,
        "messages": messages,
        "response_format": response_format,
    }

    if getattr(settings, "CHART_AI_SEED", None) is not None:
        kwargs["seed"] = int(settings.CHART_AI_SEED)

    if not _is_gpt5_family(model_name):
        temp = getattr(settings, "CHART_AI_TEMPERATURE", None)
        if temp is not None:
            kwargs["temperature"] = float(temp)

    return kwargs


class ChartAiOutput(BaseModel):
    """Validated output from the model."""
    tp1_probability: float = Field(ge=0.0, le=1.0)
    sl_before_tp_probability: float = Field(ge=0.0, le=1.0)
    trend_state: str
    momentum_bias: str
    quality_score_delta: float = Field(ge=-20.0, le=20.0)
    patterns: list[dict]


class ChartOpenAiClient:
    """
    Thin wrapper around OpenAI API for image understanding + structured JSON.
    Uses the Chat Completions or Responses API format that supports images and json_schema.
    """

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            log.info("ChartAI(OpenAI): API key not configured; client will remain inactive.")
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def analyze_chart_png(
            self,
            png_bytes: bytes,
            symbol: Optional[str],
            chain_name: Optional[str],
            pair_address: Optional[str],
            timeframe_minutes: int,
            lookback_minutes: int,
    ) -> Optional[ChartAiOutput]:
        """
        Sends the chart image to the OpenAI vision model with a strict JSON schema.
        Returns parsed ChartAiOutput, or None on failure.
        """
        if not settings.OPENAI_API_KEY:
            log.warning("ChartAI(OpenAI): missing API key.")
            return None

        model_name = settings.OPENAI_MODEL
        system_prompt = build_chartist_system_prompt()
        user_prompt = build_chartist_user_prompt(
            symbol=symbol,
            chain_name=chain_name,
            pair_address=pair_address,
            timeframe_minutes=timeframe_minutes,
            lookback_minutes=lookback_minutes,
        )

        data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

        try:
            primary_kwargs = _build_common_kwargs(
                model_name=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": chartist_json_schema(),
                },
            )
            response = self._client.chat.completions.create(**primary_kwargs)
            raw = response.choices[0].message.content
            parsed = ChartAiOutput.model_validate_json(raw)
            log.info("ChartAI(OpenAI): analysis completed (model=%s, tf=%dm)", model_name, timeframe_minutes)
            return parsed
        except Exception as exc:
            log.warning("ChartAI(OpenAI): primary call failed (%s). Falling back to json_object mode.", exc)

        try:
            fallback_kwargs = _build_common_kwargs(
                model_name=model_name,
                messages=[
                    {"role": "system", "content": system_prompt + "\nReturn a single JSON object only."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                response_format={"type": "json_object"},
            )
            response = self._client.chat.completions.create(**fallback_kwargs)
            raw = response.choices[0].message.content
            parsed = ChartAiOutput.model_validate_json(raw)
            log.info("ChartAI(OpenAI): analysis completed with JSON object mode (model=%s)", model_name)
            log.debug("ChartAI(OpenAI): raw JSON (fallback) = %s", raw)
            return parsed
        except ValidationError as ve:
            log.warning("ChartAI(OpenAI): schema validation failed: %s", ve)
            return None
        except Exception as exc:
            log.warning("ChartAI(OpenAI): fallback call failed: %s", exc)
            return None
