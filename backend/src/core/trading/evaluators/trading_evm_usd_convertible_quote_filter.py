from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from src.core.trading.screener.trading_screener_structures import TRADING_SCREENER_PROVIDER_DEXSCREENER
from src.core.trading.trading_chain_capability_service import is_trading_evm_blockchain_network
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.format_utils import tail
from src.integrations.blockchain.evm.blockchain_evm_price_reader import is_evm_quote_token_usd_convertible
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def resolve_quote_token_address_from_candidate(candidate: TradingCandidate) -> Optional[str]:
    if candidate.screener_envelope.provider_id != TRADING_SCREENER_PROVIDER_DEXSCREENER:
        return None

    try:
        token_information = DexscreenerTokenInformation.model_validate(candidate.screener_envelope.payload)
    except ValidationError:
        logger.exception(
            "[TRADING][FILTER][EVM_USD_CONVERTIBLE_QUOTE] Failed to parse dexscreener envelope for %s",
            candidate.token.symbol,
        )
        return None

    quote_token_address = token_information.quote_token.address.strip()
    if not quote_token_address:
        return None
    return quote_token_address


def apply_evm_usd_convertible_quote_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    retained: list[TradingCandidate] = []
    rejected_non_convertible_quote_count: int = 0
    rejected_missing_quote_count: int = 0
    passed_through_non_evm_count: int = 0

    for candidate in candidates:
        if not is_trading_evm_blockchain_network(candidate.token.chain):
            retained.append(candidate)
            passed_through_non_evm_count += 1
            continue

        symbol: str = candidate.token.symbol
        short_pair_address: str = tail(candidate.token.pair_address)
        quote_token_address = resolve_quote_token_address_from_candidate(candidate)

        if quote_token_address is None:
            logger.debug(
                "[TRADING][FILTER][EVM_USD_CONVERTIBLE_QUOTE] %s (%s) rejected — missing quote token address",
                symbol,
                short_pair_address,
            )
            rejected_missing_quote_count += 1
            continue

        if not is_evm_quote_token_usd_convertible(candidate.token.chain, quote_token_address):
            logger.info(
                "[TRADING][FILTER][EVM_USD_CONVERTIBLE_QUOTE] %s (%s) rejected — quote %s is not USD-convertible",
                symbol,
                short_pair_address,
                quote_token_address[:10],
            )
            rejected_non_convertible_quote_count += 1
            continue

        retained.append(candidate)

    logger.info(
        "[TRADING][FILTER][EVM_USD_CONVERTIBLE_QUOTE] Retained %d / %d candidates "
        "(rejected_non_convertible=%d, rejected_missing_quote=%d, passed_through_non_evm=%d)",
        len(retained),
        len(candidates),
        rejected_non_convertible_quote_count,
        rejected_missing_quote_count,
        passed_through_non_evm_count,
    )
    return retained
