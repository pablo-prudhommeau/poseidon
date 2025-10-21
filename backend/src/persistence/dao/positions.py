from __future__ import annotations

from typing import List, Dict

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_structures import TokenPrice
from src.persistence.models import Position, Phase
from src.persistence.serializers import serialize_position


def get_open_tokens(database_session: Session) -> List[Token]:
    """
    Return tokens (chain, symbol, token address, pair address) for all ACTIVE positions (OPEN or PARTIAL).
    """
    statement = (
        select(
            Position.chain,
            Position.symbol,
            Position.tokenAddress,
            Position.pairAddress,
        )
        .where(or_(Position.phase == Phase.OPEN, Position.phase == Phase.PARTIAL))
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
    Return all ACTIVE positions (OPEN or PARTIAL), newest first.
    """
    statement = (
        select(Position)
        .where(or_(Position.phase == Phase.OPEN, Position.phase == Phase.PARTIAL))
        .order_by(Position.opened_at.desc())
    )
    return list(database_session.execute(statement).scalars().all())


def serialize_positions_with_token_prices(
        positions: List[Position],
        token_prices: List[TokenPrice],
) -> List[dict]:
    """
    Serialize ACTIVE positions and attach a live last_price by token when available.
    """
    payload: List[dict] = []
    for position in positions:
        serialized = serialize_position(position)
        for token_price in token_prices:
            if (token_price.token.chain == position.chain
                and token_price.token.symbol == position.symbol
                and token_price.token.tokenAddress == position.tokenAddress
                and token_price.token.pairAddress == position.pairAddress
            ):
                serialized["last_price"] = token_price.priceUsd
                payload.append(serialized)
                break
    return payload
