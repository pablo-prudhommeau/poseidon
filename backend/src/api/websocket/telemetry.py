from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.api.http.api_schemas import TradingEvaluationPayload
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
    def record_analytics_event(evaluation_record: TradingEvaluation, database_session: Optional[Session] = None) -> TradingEvaluationPayload:
        logger.debug("[WEBSOCKET][TELEMETRY][RECORD] Initiating evaluation event recording process")

        def _execute_recording(session_to_use: Session) -> TradingEvaluationPayload:
            evaluation_dao = TradingEvaluationDao(session_to_use)
            evaluation_dao.save(evaluation_record)
            session_to_use.flush()
            return serialize_trading_evaluation(evaluation_record)

        if database_session is not None:
            serialized_payload = _execute_recording(database_session)
        else:
            with _session() as session:
                serialized_payload = _execute_recording(session)
                session.commit()

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
            realized_profit_and_loss_percentage: float,
            realized_profit_and_loss_usd: float,
            holding_duration_minutes: float,
            was_profitable: bool,
            exit_reason: Optional[str] = None,
            database_session: Optional[Session] = None,
    ) -> Optional[TradingEvaluationPayload]:
        logger.debug("[WEBSOCKET][TELEMETRY][OUTCOME] Initiating trade outcome linkage for trade id %s", trade_id)

        def _execute_linkage(session_to_use: Session) -> Optional[TradingEvaluationPayload]:
            evaluation_dao = TradingEvaluationDao(session_to_use)
            outcome_dao = TradingOutcomeDao(session_to_use)

            evaluation = evaluation_dao.retrieve_latest_buy_decision(token_address, closed_at.timestamp())

            if not evaluation:
                logger.warning("[WEBSOCKET][TELEMETRY][OUTCOME] Trade outcome linkage failed, no evaluation record found for token %s", token_address)
                return None

            outcome_record = TradingOutcome(
                evaluation_id=evaluation.id,
                trade_id=trade_id,
                occurred_at=closed_at,
                realized_profit_and_loss_percentage=realized_profit_and_loss_percentage,
                realized_profit_and_loss_usd=realized_profit_and_loss_usd,
                holding_duration_minutes=holding_duration_minutes,
                is_profitable=was_profitable,
                exit_reason=exit_reason,
            )

            outcome_dao.save(outcome_record)
            session_to_use.flush()

            return serialize_trading_evaluation(evaluation)

        if database_session is not None:
            serialized_payload = _execute_linkage(database_session)
        else:
            with _session() as session:
                serialized_payload = _execute_linkage(session)
                session.commit()

        if serialized_payload:
            logger.info("[WEBSOCKET][TELEMETRY][OUTCOME] Successfully linked outcome for trade id %s", trade_id)
            websocket_manager.broadcast_json_payload_threadsafe({
                "type": WebsocketMessageType.ANALYTICS.value,
                "payload": serialized_payload.model_dump(mode="json")
            })

        return serialized_payload
