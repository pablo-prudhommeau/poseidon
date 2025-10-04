from __future__ import annotations

from typing import List, Dict

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from src.persistence.models import Position, Phase
from src.persistence.serializers import serialize_position


def get_open_addresses(database_session: Session) -> List[str]:
    """
    Return lowercased addresses for all ACTIVE positions (OPEN or PARTIAL).
    Empty strings are filtered out.
    """
    rows = (
        database_session.execute(
            select(Position.address).where(
                or_(Position.phase == Phase.OPEN, Position.phase == Phase.PARTIAL)
            )
        )
        .scalars()
        .all()
    )
    return [address for address in rows if address]


def get_open_positions(database_session: Session) -> List[Position]:
    """
    Return all ACTIVE positions (OPEN or PARTIAL), newest first.
    """
    statement = (
        select(Position)
        .where(or_(Position.phase == Phase.OPEN, Position.phase == Phase.PARTIAL))
        .order_by(Position.opened_at.desc())
    )
    return list(database_session.execute(statement).scalars().all())


def serialize_positions_with_prices_by_address(
        database_session: Session,
        address_price: Dict[str, float],
) -> List[dict]:
    """
    Serialize ACTIVE positions and attach a live last_price by address when available.
    """
    positions = get_open_positions(database_session)
    payload: List[dict] = []
    for position in positions:
        last_price_value = None
        if position.address:
            last_price_value = address_price.get(position.address)
        payload.append(serialize_position(position, last_price_value))
    return payload
