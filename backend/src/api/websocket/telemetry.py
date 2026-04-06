from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.api.http.api_schemas import EvaluationPayload
from src.api.serializers import serialize_trading_evaluation
from src.api.websocket.websocket_manager import websocket_manager
from src.core.structures.structures import WebsocketMessageType
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading.trading_outcome_dao import TradingOutcomeDao
from src.persistence.db import _session
from src.persistence.models import TradingEvaluation, TradingOutcome

logger = get_application_logger(__name__)


class TelemetryService:
    @staticmethod
    def record_analytics_event(evaluation_record: TradingEvaluation) -> EvaluationPayload:
        logger.debug("[WEBSOCKET][TELEMETRY][RECORD] Initiating evaluation event recording process")

        with _session() as db:
            evaluation_dao = TradingEvaluationDao(db)
            evaluation_dao.save(evaluation_record)
            db.commit()
            serialized_payload = serialize_trading_evaluation(evaluation_record)

        logger.info("[WEBSOCKET][TELEMETRY][RECORD] Successfully recorded evaluation event")

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
    ) -> Optional[EvaluationPayload]:
        logger.debug("[WEBSOCKET][TELEMETRY][OUTCOME] Initiating trade outcome linkage for trade id %s", trade_id)

        with _session() as db:
            evaluation_dao = TradingEvaluationDao(db)
            outcome_dao = TradingOutcomeDao(db)

            evaluation = evaluation_dao.retrieve_latest_buy_decision(token_address, closed_at.timestamp())

            if not evaluation:
                logger.warning("[WEBSOCKET][TELEMETRY][OUTCOME] Trade outcome linkage failed, no evaluation record found for token %s", token_address)
                return None

            outcome_record = TradingOutcome(
                evaluation_id=evaluation.id,
                trade_id=trade_id,
                occurred_at=closed_at,
                profit_and_loss_percentage=profit_and_loss_percentage,
                profit_and_loss_usd=profit_and_loss_usd,
                holding_duration_minutes=holding_duration_minutes,
                is_profitable=was_profitable,
                exit_reason=exit_reason,
            )

            outcome_dao.save(outcome_record)
            db.commit()

            # We return the whole evaluation record with its outcomes
            serialized_payload = serialize_trading_evaluation(evaluation)

        logger.info("[WEBSOCKET][TELEMETRY][OUTCOME] Successfully linked outcome for trade id %s", trade_id)

        websocket_manager.broadcast_json_payload_threadsafe({
            "type": WebsocketMessageType.ANALYTICS.value,
            "payload": serialized_payload.model_dump(mode="json")
        })

        return serialized_payload
