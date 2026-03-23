from __future__ import annotations

from typing import List

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from src.core.structures.structures import Token
from src.persistence.models import Position, Phase


def get_open_tokens(database_session: Session) -> List[Token]:
    """
    Return tokens (chain, symbol, token address, pair address) for all ACTIVE positions.
    ACTIVE includes OPEN, PARTIAL, and STALED (visible but autosell-disabled).
    """
    statement = (
        select(
            Position.chain,
            Position.symbol,
            Position.tokenAddress,
            Position.pairAddress,
        )
        .where(
            or_(
                Position.phase == Phase.OPEN,
                Position.phase == Phase.PARTIAL,
                Position.phase == Phase.STALED,
            )
        )
        .order_by(Position.opened_at.desc())
    )
    results = database_session.execute(statement).all()
    tokens: List[Token] = []
    for chain, symbol, token_address, pair_address in results:
        tokens.append(
            Token(
                chain=chain,
                symbol=symbol,
                tokenAddress=token_address,
                pairAddress=pair_address,
            )
        )
    return tokens


def get_open_positions(database_session: Session) -> List[Position]:
    """
    Return all ACTIVE positions (OPEN, PARTIAL, STALED), newest first.
    """
    statement = (
        select(Position)
        .where(
            or_(
                Position.phase == Phase.OPEN,
                Position.phase == Phase.PARTIAL,
                Position.phase == Phase.STALED,
            )
        )
        .order_by(Position.opened_at.desc())
    )
    return list(database_session.execute(statement).scalars().all())
