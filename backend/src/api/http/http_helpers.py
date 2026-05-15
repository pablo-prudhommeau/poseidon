from typing import Optional

from requests import Session

from src.api.http.api_schemas import TradingPositionPayload
from src.api.serializers import serialize_trading_position
from src.core.trading.cache.trading_cache import trading_cache
from src.persistence.dao.trading_position_dao import TradingPositionDao


def resolve_linked_position_payload_for_evaluation(
        evaluation_id: int,
        database_session: Session,
) -> Optional[TradingPositionPayload]:
    trading_state = trading_cache.get_trading_state()
    cached_positions = trading_state.positions
    if cached_positions is not None:
        for cached_position in cached_positions:
            if cached_position.evaluation_id == evaluation_id:
                return cached_position

    position_dao = TradingPositionDao(database_session)
    position_record = position_dao.retrieve_latest_by_evaluation_id(evaluation_id)
    if position_record is None:
        return None

    last_price_candidate: Optional[float] = None
    if trading_state.position_prices is not None:
        for position_price_entry in trading_state.position_prices:
            if position_price_entry.position_id == position_record.id:
                last_price_candidate = position_price_entry.last_price
                break

    return serialize_trading_position(position_record, last_price=last_price_candidate)
