from __future__ import annotations

import asyncio
import math
import threading
from datetime import timedelta
from typing import Awaitable, Optional, Final, TypeVar

from sqlalchemy import select

from src.configuration.config import settings
from src.core.structures.structures import Candidate, ScoreComponents, Token
from src.core.utils.date_utils import get_current_local_datetime
from src.core.utils.format_utils import _tail, _format
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list_sync
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation, DexscreenerTransactionActivity
from src.logging.logger import get_logger
from src.persistence.db import _session
from src.persistence.models import Trade

logger = get_logger(__name__)

RejectionCounts = dict[str, int]

_SOFT_SORT_KEYS: Final[set[str]] = {"volume_5m", "volume_1h", "volume_6h", "volume_24h", "liquidity_usd"}

U = TypeVar("U")


def _is_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _passes_percent_thresholds(
        candidate: Candidate,
        interval: str,
        threshold_5m: float,
        threshold_1h: float,
        threshold_6h: float,
        threshold_24h: float,
) -> bool:
    percent_5m = candidate.dexscreener_token_information.price_change.m5
    percent_1h = candidate.dexscreener_token_information.price_change.h1
    percent_6h = candidate.dexscreener_token_information.price_change.h6
    percent_24h = candidate.dexscreener_token_information.price_change.h24

    if interval == "5m":
        return (percent_5m is not None and percent_5m >= threshold_5m) or (percent_24h is not None and percent_24h >= threshold_24h)
    if interval == "1h":
        return (percent_1h is not None and percent_1h >= threshold_1h) or (percent_24h is not None and percent_24h >= threshold_24h)
    if interval == "6h":
        return (percent_6h is not None and percent_6h >= threshold_6h) or (percent_24h is not None and percent_24h >= threshold_24h)
    return percent_24h is not None and percent_24h >= threshold_24h


def _passes_volume_thresholds(
        candidate: Candidate,
        interval: str,
        threshold_5m: float,
        threshold_1h: float,
        threshold_6h: float,
        threshold_24h: float,
) -> bool:
    volume_5m = candidate.dexscreener_token_information.volume.m5
    volume_1h = candidate.dexscreener_token_information.volume.h1
    volume_6h = candidate.dexscreener_token_information.volume.h6
    volume_24h = candidate.dexscreener_token_information.volume.h24

    if interval == "5m":
        return (volume_5m is not None and volume_5m >= threshold_5m) or (volume_24h is not None and volume_24h >= threshold_24h)
    if interval == "1h":
        return (volume_1h is not None and volume_1h >= threshold_1h) or (volume_24h is not None and volume_24h >= threshold_24h)
    if interval == "6h":
        return (volume_6h is not None and volume_6h >= threshold_6h) or (volume_24h is not None and volume_24h >= threshold_24h)
    return volume_24h is not None and volume_24h >= threshold_24h


def _has_valid_intraday_bars(candidate: Candidate) -> bool:
    return (
            _is_number(candidate.dexscreener_token_information.price_change.m5)
            and _is_number(candidate.dexscreener_token_information.price_change.h1)
            and _is_number(candidate.dexscreener_token_information.price_change.h6)
            and _is_number(candidate.dexscreener_token_information.price_change.h24)
    )


def _momentum_ok(
        percent_5m: Optional[float],
        percent_1h: Optional[float],
        percent_6h: Optional[float],
        percent_24h: Optional[float]
) -> bool:
    maximum_absolute_percent_5m = float(settings.DEXSCREENER_MAX_ABS_M5_PCT)
    maximum_absolute_percent_1h = float(settings.DEXSCREENER_MAX_ABS_H1_PCT)
    maximum_absolute_percent_6h = float(settings.DEXSCREENER_MAX_ABS_H6_PCT)
    maximum_absolute_percent_24h = float(settings.DEXSCREENER_MAX_ABS_H24_PCT)

    if percent_5m is not None and abs(percent_5m) > maximum_absolute_percent_5m:
        return False
    if percent_1h is not None and abs(percent_1h) > maximum_absolute_percent_1h:
        return False
    if percent_6h is not None and abs(percent_6h) > maximum_absolute_percent_6h:
        return False
    if percent_24h is not None and abs(percent_24h) > maximum_absolute_percent_24h:
        return False
    return True


def _candidate_from_dexscreener_token_information(token_information: DexscreenerTokenInformation) -> Candidate:
    return Candidate(
        quality_score=0.0,
        statistics_score=0.0,
        entry_score=0.0,
        score_final=0.0,
        score_components=ScoreComponents(
            quality_score=0.0,
            statistics_score=0.0,
            entry_score=0.0,
        ),
        ai_quality_delta=0.0,
        ai_buy_probability=0.0,
        dexscreener_token_information=token_information,
        token=Token(
            symbol=token_information.base_token.symbol,
            chain=token_information.chain_id,
            token_address=token_information.base_token.address,
            pair_address=token_information.pair_address
        ),
    )


def _get_candidate_sort_value(candidate: Candidate, sort_key: str) -> float:
    if sort_key == "liquidity_usd":
        return candidate.dexscreener_token_information.liquidity.usd
    return candidate.dexscreener_token_information.volume.h24


def _buy_sell_score(transaction_activity: DexscreenerTransactionActivity) -> float:
    activity_bucket = transaction_activity.h1 or transaction_activity.h24
    buys = activity_bucket.buys
    sells = activity_bucket.sells
    total_transactions = buys + sells

    if total_transactions <= 0:
        return 0.5
    return buys / total_transactions


def filter_strict(
        candidates: list[Candidate],
        interval: str,
        volume_threshold_5m: float,
        volume_threshold_1h: float,
        volume_threshold_6h: float,
        volume_threshold_24h: float,
        minimum_liquidity_usd: float,
        percent_threshold_5m: float,
        percent_threshold_1h: float,
        percent_threshold_6h: float,
        percent_threshold_24h: float,
        maximum_results: int,
) -> tuple[list[Candidate], RejectionCounts]:
    retained_candidates: list[Candidate] = []
    rejection_statistics: RejectionCounts = {
        "excluded": 0,
        "low_volume": 0,
        "low_liquidity": 0,
        "low_percent": 0
    }

    for candidate in candidates:
        symbol = candidate.dexscreener_token_information.base_token.symbol
        liquidity_usd = candidate.dexscreener_token_information.liquidity.usd

        if not _passes_volume_thresholds(
                candidate=candidate,
                interval=interval,
                threshold_5m=volume_threshold_5m,
                threshold_1h=volume_threshold_1h,
                threshold_6h=volume_threshold_6h,
                threshold_24h=volume_threshold_24h
        ):
            logger.debug("[TRENDING][FILTER][STRICT][REJECT] Token %s fails volume thresholds for interval %s", symbol, interval)
            rejection_statistics["low_volume"] += 1
            continue

        if liquidity_usd < minimum_liquidity_usd:
            logger.debug("[TRENDING][FILTER][STRICT][REJECT] Token %s fails liquidity thresholds with %f USD against minimum %f USD", symbol, liquidity_usd, minimum_liquidity_usd)
            rejection_statistics["low_liquidity"] += 1
            continue

        if not _passes_percent_thresholds(
                candidate=candidate,
                interval=interval,
                threshold_5m=percent_threshold_5m,
                threshold_1h=percent_threshold_1h,
                threshold_6h=percent_threshold_6h,
                threshold_24h=percent_threshold_24h
        ):
            logger.debug("[TRENDING][FILTER][STRICT][REJECT] Token %s fails percent thresholds for interval %s", symbol, interval)
            rejection_statistics["low_percent"] += 1
            continue

        retained_candidates.append(candidate)
        if len(retained_candidates) >= maximum_results:
            logger.info("[TRENDING][FILTER][STRICT][LIMIT] Reached maximum allowed results of %d candidates", maximum_results)
            break

    for candidate in retained_candidates:
        symbol = candidate.dexscreener_token_information.base_token.symbol
        short_address = _tail(candidate.dexscreener_token_information.base_token.address)

        volume_5m_usd = candidate.dexscreener_token_information.volume.m5
        volume_1h_usd = candidate.dexscreener_token_information.volume.h1
        volume_6h_usd = candidate.dexscreener_token_information.volume.h6
        volume_24h_usd = candidate.dexscreener_token_information.volume.h24

        liquidity_usd = candidate.dexscreener_token_information.liquidity.usd

        percent_5m = candidate.dexscreener_token_information.price_change.m5
        percent_1h = candidate.dexscreener_token_information.price_change.h1
        percent_6h = candidate.dexscreener_token_information.price_change.h6
        percent_24h = candidate.dexscreener_token_information.price_change.h24

        matching_interval = "24h"
        if interval == "5m" and percent_5m is not None and percent_5m >= percent_threshold_5m:
            matching_interval = "5m"
        elif interval == "1h" and percent_1h is not None and percent_1h >= percent_threshold_1h:
            matching_interval = "1h"
        elif interval == "6h" and percent_6h is not None and percent_6h >= percent_threshold_6h:
            matching_interval = "6h"
        elif percent_24h is not None and percent_24h >= percent_threshold_24h:
            matching_interval = "24h"

        logger.debug(
            "[TRENDING][FILTER][STRICT][RETAIN] Token %s (%s) matches interval %s. Volume: 5m=%f, 1h=%f, 6h=%f, 24h=%f. Liquidity: %f USD. Percent: 5m=%s, 1h=%s, 6h=%s, 24h=%s.",
            symbol,
            short_address,
            matching_interval,
            volume_5m_usd,
            volume_1h_usd,
            volume_6h_usd,
            volume_24h_usd,
            liquidity_usd,
            _format(percent_5m),
            _format(percent_1h),
            _format(percent_6h),
            _format(percent_24h),
        )

    return retained_candidates, rejection_statistics


def soft_fill(
        candidate_universe: list[Candidate],
        retained_candidates: list[Candidate],
        minimum_required_candidates: int,
        minimum_liquidity_usd: float,
        sort_key: str,
) -> list[Candidate]:
    if minimum_required_candidates <= 0 or len(retained_candidates) >= minimum_required_candidates:
        return retained_candidates

    retained_candidate_addresses: set[str] = {
        candidate.dexscreener_token_information.base_token.address
        for candidate in retained_candidates
        if candidate.dexscreener_token_information.base_token.address
    }
    candidate_pool: list[Candidate] = []

    for candidate in candidate_universe:
        address = candidate.dexscreener_token_information.base_token.address
        if address and address in retained_candidate_addresses:
            continue

        volume_5m = candidate.dexscreener_token_information.volume.m5
        volume_1h = candidate.dexscreener_token_information.volume.h1
        volume_6h = candidate.dexscreener_token_information.volume.h6
        volume_24h = candidate.dexscreener_token_information.volume.h24

        if (
                volume_5m is None
                or volume_1h is None
                or volume_6h is None
                or volume_24h is None
                or (volume_5m < 0.0 and volume_1h < 0.0 and volume_6h < 0.0 and volume_24h < 0.0)
        ):
            continue

        percent_5m = candidate.dexscreener_token_information.price_change.m5
        percent_1h = candidate.dexscreener_token_information.price_change.h1
        percent_6h = candidate.dexscreener_token_information.price_change.h6
        percent_24h = candidate.dexscreener_token_information.price_change.h24

        if (
                percent_1h is not None
                and percent_5m is not None
                and percent_6h is not None
                and percent_24h is not None
                and (percent_1h < 0.0 and percent_24h < 0.0 and percent_5m < 0.0 and percent_6h < 0.0)
        ):
            continue

        candidate_pool.append(candidate)

    resolved_sort_key = sort_key if sort_key in _SOFT_SORT_KEYS else "volume_24h"
    candidate_pool.sort(key=lambda candidate_item: _get_candidate_sort_value(candidate=candidate_item, sort_key=resolved_sort_key), reverse=True)

    for candidate in candidate_pool:
        if len(retained_candidates) >= minimum_required_candidates:
            break

        logger.debug(
            "[TRENDING][FILTER][SOFT_FILL][RETAIN] Token %s retained to meet minimum threshold. Volume 24h: %f, Liquidity: %f, Percent 5m: %s, 1h: %s, 6h: %s, 24h: %s",
            candidate.dexscreener_token_information.base_token.symbol,
            candidate.dexscreener_token_information.volume.h24,
            candidate.dexscreener_token_information.liquidity.usd,
            candidate.dexscreener_token_information.price_change.m5,
            candidate.dexscreener_token_information.price_change.h1,
            candidate.dexscreener_token_information.price_change.h6,
            candidate.dexscreener_token_information.price_change.h24,
        )
        retained_candidates.append(candidate)
        if candidate.dexscreener_token_information.base_token.address:
            retained_candidate_addresses.add(candidate.dexscreener_token_information.base_token.address)

    return retained_candidates


def recently_traded(address: str, time_window_minutes: int = 45) -> bool:
    if not address:
        return False

    with _session() as database_session:
        database_query = (
            select(Trade)
            .where(Trade.token_address == address)
            .order_by(Trade.created_at.desc())
        )
        trade_record = database_session.execute(database_query).scalars().first()
        if not trade_record:
            return False

        current_time = get_current_local_datetime()
        trade_creation_time = trade_record.created_at.astimezone()
        return (current_time - trade_creation_time) < timedelta(minutes=time_window_minutes)


def preload_best_prices(candidates: list[Candidate]) -> list[DexscreenerTokenInformation]:
    if not candidates:
        return []

    unique_tokens: list[Token] = []
    processed_token_identifiers: set[tuple[str, str, str, str]] = set()

    for candidate in candidates:
        token_identifier = (
            candidate.dexscreener_token_information.base_token.symbol or "",
            candidate.dexscreener_token_information.chain_id or "",
            candidate.dexscreener_token_information.base_token.address or "",
            candidate.dexscreener_token_information.pair_address or "",
        )

        if token_identifier in processed_token_identifiers:
            continue

        processed_token_identifiers.add(token_identifier)
        unique_tokens.append(
            Token(
                symbol=candidate.dexscreener_token_information.base_token.symbol,
                chain=candidate.dexscreener_token_information.chain_id,
                token_address=candidate.dexscreener_token_information.base_token.address,
                pair_address=candidate.dexscreener_token_information.pair_address
            )
        )

    if not unique_tokens:
        return []

    return fetch_dexscreener_token_information_list_sync(unique_tokens)


def get_price_from_token_information_list(token_information_list: list[DexscreenerTokenInformation], candidate: Candidate) -> Optional[float]:
    for token_information in token_information_list:
        if (
                token_information.base_token.symbol == candidate.dexscreener_token_information.base_token.symbol
                and token_information.chain_id == candidate.dexscreener_token_information.chain_id
                and token_information.base_token.address == candidate.dexscreener_token_information.base_token.address
                and token_information.pair_address == candidate.dexscreener_token_information.pair_address
        ):
            return token_information.price_usd
    return None


def _run_awaitable_in_fresh_loop(asynchronous_task: Awaitable[U], debug_label: str = "") -> U:
    try:
        return asyncio.run(asynchronous_task)
    except RuntimeError as runtime_exception:
        exception_message = str(runtime_exception)
        if ("Event loop is closed" not in exception_message) and ("cannot be called from a running event loop" not in exception_message):
            raise

        resolved_label = debug_label or "asynchronous_task"
        logger.debug("[TRENDING][ASYNC][EXECUTION] Event loop constraint detected for task %s with message: %s. Re-running in an isolated thread and event loop.", resolved_label, exception_message)

        task_result_container: dict[str, U] = {}
        task_error_container: dict[str, BaseException] = {}

        def isolated_runner() -> None:
            isolated_event_loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(isolated_event_loop)
                task_result_container["result"] = isolated_event_loop.run_until_complete(asynchronous_task)
                try:
                    isolated_event_loop.run_until_complete(isolated_event_loop.shutdown_asyncgens())
                except Exception:
                    pass
            except BaseException as execution_error:
                task_error_container["error"] = execution_error
            finally:
                try:
                    asyncio.set_event_loop(None)
                except Exception:
                    pass
                isolated_event_loop.close()

        isolated_thread = threading.Thread(target=isolated_runner, name=f"isolated-loop-{resolved_label}", daemon=True)
        isolated_thread.start()
        isolated_thread.join()

        if "error" in task_error_container:
            raise task_error_container["error"]
        return task_result_container["result"]


def fetch_trending_candidates_sync() -> list[Candidate]:
    from src.integrations.dexscreener.dexscreener_client import fetch_trending_candidates

    token_information_list: list[DexscreenerTokenInformation] = _run_awaitable_in_fresh_loop(
        asynchronous_task=fetch_trending_candidates(),
        debug_label="fetch_trending_candidates",
    )
    candidates_list: list[Candidate] = [_candidate_from_dexscreener_token_information(token_information) for token_information in token_information_list]
    logger.info("[TRENDING][FETCH][SUCCESS] Successfully converted %d normalized rows into candidate entities.", len(candidates_list))
    return candidates_list


def is_address_in_open_positions(candidate_address: str, open_position_addresses: set[str]) -> bool:
    return bool(candidate_address) and candidate_address in open_position_addresses
