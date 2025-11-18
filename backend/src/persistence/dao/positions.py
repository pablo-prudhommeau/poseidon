from __future__ import annotations

from typing import List, cast

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.persistence.models import Position, Phase
from src.persistence.serializers import serialize_position


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


def serialize_positions_with_token_information(
        positions: List[Position],
        token_information_list: List[DexscreenerTokenInformation],
) -> List[dict]:
    """
    Serialize ACTIVE positions and attach a live last_price by token when available.
    """
    payload: List[dict] = []
    for position in positions:
        serialized = serialize_position(position)
        for token_information in token_information_list:
            if (
                    token_information.chain_id == position.chain
                    and token_information.base_token.symbol == position.symbol
                    and token_information.base_token.address == position.tokenAddress
                    and token_information.pair_address == position.pairAddress
            ):
                if token_information.price_usd is not None:
                    serialized["last_price"] = float(token_information.price_usd)
                payload.append(cast(dict, serialized))
                break
    return payload
