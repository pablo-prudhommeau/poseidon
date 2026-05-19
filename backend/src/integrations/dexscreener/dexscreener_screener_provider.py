from __future__ import annotations

from src.core.structures.structures import Token
from src.core.trading.screener.trading_screener_structures import (
    TRADING_SCREENER_PROVIDER_DEXSCREENER,
    TradingScreenerEnvelope,
)
from src.core.trading.trading_helpers import build_trading_candidate
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.dexscreener.dexscreener_client import (
    fetch_dexscreener_token_information_list_sync,
    fetch_trending_candidates,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.integrations.dexscreener.dexscreener_utils import (
    index_dexscreener_token_information_list,
    map_token_information_to_trading_market_snapshot,
    map_token_information_to_trading_token,
    resolve_dexscreener_token_information_for_token,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class DexscreenerScreenerProvider:
    @property
    def provider_id(self) -> str:
        return TRADING_SCREENER_PROVIDER_DEXSCREENER

    def fetch_trending_candidates(self) -> list[TradingCandidate]:
        from src.core.trading.trading_utils import run_awaitable_in_fresh_loop

        token_information_list: list[DexscreenerTokenInformation] = run_awaitable_in_fresh_loop(
            asynchronous_task=fetch_trending_candidates(),
            debug_label="fetch_trending_candidates",
        )
        return self._build_candidates_from_dexscreener_records(token_information_list)

    def refresh_candidates(self, candidates: list[TradingCandidate]) -> None:
        if not candidates:
            return

        unique_tokens: list[Token] = []
        processed_token_identifiers: set[tuple[str, str, str, str]] = set()

        for candidate in candidates:
            token = candidate.token
            token_identifier = (
                token.symbol,
                token.chain,
                token.token_address,
                token.pair_address,
            )
            if token_identifier in processed_token_identifiers:
                continue
            processed_token_identifiers.add(token_identifier)
            unique_tokens.append(token)

        if not unique_tokens:
            return

        token_information_list = fetch_dexscreener_token_information_list_sync(unique_tokens)
        indexed_records = index_dexscreener_token_information_list(token_information_list)

        refreshed_count = 0
        for candidate in candidates:
            token_information = resolve_dexscreener_token_information_for_token(indexed_records, candidate.token)
            if token_information is None:
                logger.debug(
                    "[TRADING][SCREENER][DEXSCREENER][REFRESH] No payload for %s — keeping prior market snapshot",
                    candidate.token.symbol,
                )
                continue
            try:
                _apply_dexscreener_record_to_candidate(candidate, token_information)
                refreshed_count += 1
            except ValueError as error:
                logger.debug(
                    "[TRADING][SCREENER][DEXSCREENER][REFRESH] Skipping refresh for %s — incomplete market snapshot: %s",
                    candidate.token.symbol,
                    error,
                )

        logger.info(
            "[TRADING][SCREENER][DEXSCREENER][REFRESH] Refreshed %d / %d candidates",
            refreshed_count,
            len(candidates),
        )

    def _build_candidates_from_dexscreener_records(
            self,
            token_information_list: list[DexscreenerTokenInformation],
    ) -> list[TradingCandidate]:
        candidates: list[TradingCandidate] = []
        for token_information in token_information_list:
            try:
                candidates.append(_build_candidate_from_dexscreener_record(token_information))
            except ValueError as error:
                logger.debug(
                    "[TRADING][SCREENER][DEXSCREENER][FETCH] Skipping %s — incomplete market snapshot: %s",
                    token_information.base_token.symbol,
                    error,
                )
        return candidates


def _build_screener_envelope_from_dexscreener_record(
        token_information: DexscreenerTokenInformation,
) -> TradingScreenerEnvelope:
    return TradingScreenerEnvelope(
        provider_id=TRADING_SCREENER_PROVIDER_DEXSCREENER,
        payload=token_information.model_dump(mode="json"),
    )


def _build_candidate_from_dexscreener_record(
        token_information: DexscreenerTokenInformation,
) -> TradingCandidate:
    return build_trading_candidate(
        token=map_token_information_to_trading_token(token_information),
        market_snapshot=map_token_information_to_trading_market_snapshot(token_information),
        screener_envelope=_build_screener_envelope_from_dexscreener_record(token_information),
    )


def _apply_dexscreener_record_to_candidate(
        candidate: TradingCandidate,
        token_information: DexscreenerTokenInformation,
) -> None:
    candidate.market_snapshot = map_token_information_to_trading_market_snapshot(token_information)
    candidate.screener_envelope = _build_screener_envelope_from_dexscreener_record(token_information)
