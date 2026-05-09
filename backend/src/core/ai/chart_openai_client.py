from __future__ import annotations

import base64
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from src.configuration.config import settings
from src.core.ai.chart_prompt import (
    build_chartist_system_prompt,
    build_chartist_user_prompt,
    chartist_json_schema
)
from src.core.ai.chart_structures import ChartAiOutput
from src.core.structures.structures import BlockchainNetwork
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class ChartOpenAiClient:
    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            logger.info("[AI][OPENAI][INIT] API key not configured, client will remain inactive")

        self._openai_internal_client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def analyze_chart_vision(
            self,
            screenshot_bytes: bytes,
            symbol: Optional[str],
            chain: Optional[BlockchainNetwork],
            pair_address: Optional[str],
            timeframe_minutes: int,
            lookback_minutes: int,
    ) -> Optional[ChartAiOutput]:
        if not settings.OPENAI_API_KEY:
            logger.warning("[AI][OPENAI][AUTH] Aborting analysis: missing OpenAI API key")
            return None

        target_model = settings.OPENAI_MODEL
        system_instructions = build_chartist_system_prompt()
        user_instructions = build_chartist_user_prompt(
            symbol=symbol,
            chain_name=chain.value if chain else None,
            pair_address=pair_address,
            timeframe_minutes=timeframe_minutes,
            lookback_minutes=lookback_minutes,
        )

        base64_image_payload = base64.b64encode(screenshot_bytes).decode("ascii")
        data_url_payload = f"data:image/png;base64,{base64_image_payload}"

        try:
            chat_completion_response = self._openai_internal_client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_instructions},
                        {"type": "image_url", "image_url": {"url": data_url_payload}},
                    ]},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": chartist_json_schema(),
                },
            )

            raw_content = chat_completion_response.choices[0].message.content
            if not raw_content:
                return None

            validated_output = ChartAiOutput.model_validate_json(raw_content)
            logger.info(
                "[AI][OPENAI][ANALYSIS] Vision analysis completed with schema mode (model=%s, timeframe=%sm)",
                target_model,
                timeframe_minutes
            )
            return validated_output

        except Exception as exception:
            logger.warning(
                "[AI][OPENAI][ANALYSIS] Primary schema-based call failed, attempting fallback to json_object mode",
                exception
            )

        try:
            fallback_completion_response = self._openai_internal_client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": f"{system_instructions}\nReturn a single JSON object only."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_instructions},
                            {"type": "image_url", "image_url": {"url": data_url_payload}},
                        ],
                    },
                ],
                response_format={"type": "json_object"},
            )

            raw_fallback_content = fallback_completion_response.choices[0].message.content
            if not raw_fallback_content:
                return None

            validated_fallback_output = ChartAiOutput.model_validate_json(raw_fallback_content)
            logger.info("[AI][OPENAI][ANALYSIS] Vision analysis completed via fallback JSON object mode")
            return validated_fallback_output

        except ValidationError as validation_exception:
            logger.warning(
                "[AI][OPENAI][SCHEMA] Fallback output failed Pydantic schema validation",
                validation_exception
            )
            return None
        except Exception as general_exception:
            logger.warning(
                "[AI][OPENAI][ANALYSIS] Fallback analysis call failed completely",
                general_exception
            )
            return None
