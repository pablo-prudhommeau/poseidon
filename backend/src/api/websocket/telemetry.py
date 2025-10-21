from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from src.api.websocket.ws_manager import ws_manager
from src.logging.logger import get_logger
from src.persistence.dao.analytics import insert_analytics, attach_outcome_for_trade
from src.persistence.db import _session
from src.persistence.models import Analytics
from src.persistence.serializers import serialize_analytics

log = get_logger(__name__)


class TelemetryService:
    """
    Persistance + diffusion WebSocket des analytics.

    IMPORTANT : les événements live sont alignés sur le reste du flux:
      → { "type": "analytics", "payload": <row> }
    """

    @staticmethod
    def record_analytics_event(analytics: Analytics) -> Dict[str, Any]:
        """
        Persiste une ligne analytics et diffuse un événement WebSocket 'analytics'.
        Toutes les colonnes sont remplies (0.0 / {} par défaut).
        """
        with _session() as db:
            insert_analytics(db, analytics)
            data = serialize_analytics(analytics)

        ws_manager.broadcast_json_threadsafe({"type": "analytics", "payload": data})
        return data

    @staticmethod
    def link_trade_outcome(
            token_address: str,
            trade_id: int,
            closed_at: datetime,
            pnl_pct: float,
            pnl_usd: float,
            holding_minutes: float,
            was_profit: bool,
            exit_reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Rattache un outcome réalisé à la dernière ligne analytics du token
        et rediffuse un événement 'analytics' (alignement).
        """
        with _session() as db:
            row = attach_outcome_for_trade(
                db,
                address=token_address,
                closed_at=closed_at,
                trade_id=trade_id,
                pnl_pct=pnl_pct,
                pnl_usd=pnl_usd,
                holding_minutes=holding_minutes,
                was_profit=was_profit,
                exit_reason=exit_reason,
            )
            if not row:
                return None
            data = serialize_analytics(row)

        ws_manager.broadcast_json_threadsafe({"type": "analytics", "payload": data})
        return data
