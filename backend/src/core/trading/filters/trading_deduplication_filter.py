from typing import Set, Tuple

from src.core.trading.trading_structures import TradingCandidate
from src.core.trading.utils.trading_candidate_utils import is_address_in_open_positions
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.db import get_database_session

logger = get_application_logger(__name__)


def _load_open_position_identifiers() -> Tuple[Set[str], Set[str]]:
    with get_database_session() as database_session:
        position_dao = TradingPositionDao(database_session)
        positions = position_dao.retrieve_open_positions()
        open_symbols = {(position.token_symbol or "").upper() for position in positions if position.token_symbol}
        open_addresses: Set[str] = {position.token_address for position in positions if position.token_address}
        return open_symbols, open_addresses


def apply_deduplication_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    open_symbols, open_addresses = _load_open_position_identifiers()
    retained: list[TradingCandidate] = []

    for candidate in candidates:
        symbol_upper = candidate.dexscreener_token_information.base_token.symbol.upper()
        token_address = candidate.dexscreener_token_information.base_token.address

        if symbol_upper in open_symbols or is_address_in_open_positions(token_address, open_addresses):
            logger.debug(
                "[TRADING][FILTER][DEDUP] Skip already open %s (%s)",
                candidate.dexscreener_token_information.base_token.symbol, token_address,
            )
            continue

        retained.append(candidate)

    if not retained:
        logger.debug("[TRADING][FILTER][DEDUP] Zero candidates after deduplication")
    else:
        logger.info("[TRADING][FILTER][DEDUP] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
