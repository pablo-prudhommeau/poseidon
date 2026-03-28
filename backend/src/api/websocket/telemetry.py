from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.api.http.api_schemas import AnalyticsPayload
from src.api.serializers import serialize_analytics
from src.api.websocket.ws_manager import ws_manager
from src.logging.logger import get_logger
from src.persistence.dao.analytics import insert_analytics_record, attach_trade_outcome_to_analytics
from src.persistence.db import _session
from src.persistence.models import Analytics

logger = get_logger(__name__)


class TelemetryService:
    @staticmethod
    def record_analytics_event(analytics_record: Analytics) -> AnalyticsPayload:
        logger.debug("[WEBSOCKET][TELEMETRY][RECORD] Initiating analytics event recording process")

        with _session() as db:
            insert_analytics_record(db, analytics_record)
            serialized_payload = serialize_analytics(analytics_record)

        logger.info("[WEBSOCKET][TELEMETRY][RECORD] Successfully recorded analytics event")

        ws_manager.broadcast_json_payload_threadsafe({
            "type": "analytics",
            "payload": serialized_payload.model_dump(mode="json")
        })

        return serialized_payload

    @staticmethod
    def link_trade_outcome(
            token_address: str,
            trade_id: int,
            closed_at: datetime,
            pnl_pct: float,
            pnl_usd: float,
            holding_minutes: float,
            was_profit: bool,
            exit_reason: Optional[str] = None,
    ) -> Optional[AnalyticsPayload]:
        logger.debug("[WEBSOCKET][TELEMETRY][OUTCOME] Initiating trade outcome linkage for trade id %s", trade_id)

        with _session() as db:
            analytics_record = attach_trade_outcome_to_analytics(
                db,
                token_address=token_address,
                closed_at_timestamp=closed_at,
                trade_identifier=trade_id,
                profit_and_loss_percentage=pnl_pct,
                profit_and_loss_usd=pnl_usd,
                holding_duration_minutes=holding_minutes,
                was_profitable=was_profit,
                exit_reason=exit_reason,
            )

            if not analytics_record:
                logger.warning("[WEBSOCKET][TELEMETRY][OUTCOME] Trade outcome linkage failed, no analytics record found for trade id %s", trade_id)
                return None

            serialized_payload = serialize_analytics(analytics_record)

        logger.info("[WEBSOCKET][TELEMETRY][OUTCOME] Successfully linked outcome for trade id %s", trade_id)

        ws_manager.broadcast_json_payload_threadsafe({
            "type": "analytics",
            "payload": serialized_payload.model_dump(mode="json")
        })

        return serialized_payload
