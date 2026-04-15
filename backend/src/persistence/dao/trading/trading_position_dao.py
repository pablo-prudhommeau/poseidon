from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.persistence.models import TradingPosition, PositionPhase


class TradingPositionDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def retrieve_open_position_tokens(self) -> List[str]:
        database_query = select(TradingPosition.token_address).where(TradingPosition.current_quantity > 0)
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_open_positions(self) -> List[TradingPosition]:
        database_query = select(TradingPosition).where(TradingPosition.current_quantity > 0)
        return list(self.database_session.execute(database_query).scalars().all())

    def get_by_id(self, position_id: int) -> Optional[TradingPosition]:
        return self.database_session.get(TradingPosition, position_id)

    def save(self, trading_position: TradingPosition) -> TradingPosition:
        self.database_session.add(trading_position)
        self.database_session.flush()
        return trading_position

    def retrieve_by_phase(self, target_phase: PositionPhase) -> List[TradingPosition]:
        database_query = select(TradingPosition).where(TradingPosition.position_phase == target_phase)
        return list(self.database_session.execute(database_query).scalars().all())
