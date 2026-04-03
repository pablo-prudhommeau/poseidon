from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.api.http.api_schemas import AnalyticsPayload
from src.api.serializers import serialize_analytics
from src.api.websocket.websocket_manager import websocket_manager
from src.core.structures.structures import WebsocketMessageType
from src.logging.logger import get_application_logger
from src.persistence.dao.analytics import insert_analytics_record, attach_trade_outcome_to_analytics
from src.persistence.db import _session
from src.persistence.models import Analytics

logger = get_application_logger(__name__)


class TelemetryService:
    @staticmethod
    def record_analytics_event(analytics_record: Analytics) -> AnalyticsPayload:
        logger.debug("[WEBSOCKET][TELEMETRY][RECORD] Initiating analytics event recording process")

        with _session() as db:
            insert_analytics_record(db, analytics_record)
            serialized_payload = serialize_analytics(analytics_record)

        logger.info("[WEBSOCKET][TELEMETRY][RECORD] Successfully recorded analytics event")

        websocket_manager.broadcast_json_payload_threadsafe({
            "type": WebsocketMessageType.ANALYTICS.value,
            "payload": serialized_payload.model_dump(mode="json")
        })

        return serialized_payload

    @staticmethod
    def link_trade_outcome(
            token_address: str,
            trade_id: int,
            closed_at: datetime,
            profit_and_loss_percentage: float,
            profit_and_loss_usd: float,
            holding_duration_minutes: float,
            was_profitable: bool,
            exit_reason: Optional[str] = None,
    ) -> Optional[AnalyticsPayload]:
        logger.debug("[WEBSOCKET][TELEMETRY][OUTCOME] Initiating trade outcome linkage for trade id %s", trade_id)

        with _session() as db:
            analytics_record = attach_trade_outcome_to_analytics(
                db,
                token_address=token_address,
                closed_at_timestamp=closed_at,
                trade_identifier=trade_id,
                profit_and_loss_percentage=profit_and_loss_percentage,
                profit_and_loss_usd=profit_and_loss_usd,
                holding_duration_minutes=holding_duration_minutes,
                was_profitable=was_profitable,
                exit_reason=exit_reason,
            )

            if not analytics_record:
                logger.warning("[WEBSOCKET][TELEMETRY][OUTCOME] Trade outcome linkage failed, no analytics record found for trade id %s", trade_id)
                return None

            serialized_payload = serialize_analytics(analytics_record)

        logger.info("[WEBSOCKET][TELEMETRY][OUTCOME] Successfully linked outcome for trade id %s", trade_id)

        websocket_manager.broadcast_json_payload_threadsafe({
            "type": WebsocketMessageType.ANALYTICS.value,
            "payload": serialized_payload.model_dump(mode="json")
        })

        return serialized_payload
