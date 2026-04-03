from __future__ import annotations

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from src.core.structures.structures import Token
from src.logging.logger import get_application_logger
from src.persistence.models import Position, PositionPhase

logger = get_application_logger(__name__)


def retrieve_open_position_tokens(database_session: Session) -> list[Token]:
    logger.debug("[DATABASE][DAO][POSITIONS][TOKENS] Retrieving all tokens associated with open, partial, or staled positions")
    database_query = (
        select(
            Position.blockchain_network,
            Position.token_symbol,
            Position.token_address,
            Position.pair_address,
        )
        .where(
            or_(
                Position.position_phase == PositionPhase.OPEN,
                Position.position_phase == PositionPhase.PARTIAL,
                Position.position_phase == PositionPhase.STALED,
            )
        )
        .order_by(Position.opened_at.desc())
    )
    query_results = database_session.execute(database_query).all()
    extracted_tokens: list[Token] = []

    for chain, symbol, token_address, pair_address in query_results:
        extracted_tokens.append(
            Token(
                chain=chain,
                symbol=symbol,
                token_address=token_address,
                pair_address=pair_address,
            )
        )

    logger.debug("[DATABASE][DAO][POSITIONS][TOKENS] Successfully retrieved %d active tokens", len(extracted_tokens))
    return extracted_tokens


def retrieve_open_positions(database_session: Session) -> list[Position]:
    logger.debug("[DATABASE][DAO][POSITIONS] Retrieving all open, partial, or staled position records")
    database_query = (
        select(Position)
        .where(
            or_(
                Position.position_phase == PositionPhase.OPEN,
                Position.position_phase == PositionPhase.PARTIAL,
                Position.position_phase == PositionPhase.STALED,
            )
        )
        .order_by(Position.opened_at.desc())
    )
    active_positions = list(database_session.execute(database_query).scalars().all())

    logger.debug("[DATABASE][DAO][POSITIONS] Successfully retrieved %d active position records", len(active_positions))
    return active_positions
