from __future__ import annotations

from typing import List, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.persistence.models import Position, Phase
from src.persistence.serializers import serialize_position


def get_open_addresses(db: Session) -> List[str]:
    """Return lowercased addresses for all open positions (empty strings excluded)."""
    rows = db.execute(
        select(Position.address).where(Position.phase == Phase.OPEN)
    ).scalars().all()
    return [addr for addr in rows if addr]


def get_open_positions(db: Session) -> List[Position]:
    """Return all open positions, newest first."""
    stmt = (
        select(Position)
        .where(Position.phase == Phase.OPEN)
        .order_by(Position.opened_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def serialize_positions_with_prices_by_address(db: Session, address_price: Dict[str, float]) -> List[dict]:
    """Serialize open positions and attach a live last_price by address when available."""
    positions = get_open_positions(db)
    payload: List[dict] = []
    for position in positions:
        last_price = None
        if position.address:
            last_price = address_price.get((position.address or "").lower())
        payload.append(serialize_position(position, last_price))
    return payload
