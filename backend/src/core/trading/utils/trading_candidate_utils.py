from __future__ import annotations

import asyncio
import math
import threading
from typing import Awaitable, Optional, TypeVar

from src.core.structures.structures import Token
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

U = TypeVar("U")


def is_finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def candidate_from_dexscreener_token_information(token_information: DexscreenerTokenInformation) -> TradingCandidate:
    return TradingCandidate(
        quality_score=0.0,
        ai_adjusted_quality_score=0.0,
        ai_quality_delta=0.0,
        ai_buy_probability=0.0,
        dexscreener_token_information=token_information,
        token=Token(
            symbol=token_information.base_token.symbol,
            chain=token_information.chain_id,
            token_address=token_information.base_token.address,
            pair_address=token_information.pair_address,
            dex_id=token_information.dex_id,
        ),
    )


def get_price_from_token_information_list(
        token_information_list: list[DexscreenerTokenInformation],
        candidate: TradingCandidate,
) -> Optional[float]:
    for token_information in token_information_list:
        if (
                token_information.base_token.symbol == candidate.dexscreener_token_information.base_token.symbol
                and token_information.chain_id == candidate.dexscreener_token_information.chain_id
                and token_information.base_token.address == candidate.dexscreener_token_information.base_token.address
                and token_information.pair_address == candidate.dexscreener_token_information.pair_address
        ):
            return token_information.price_usd
    return None


def preload_best_prices(candidates: list[TradingCandidate]) -> list[DexscreenerTokenInformation]:
    from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list_sync

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
                pair_address=candidate.dexscreener_token_information.pair_address,
                dex_id=candidate.dexscreener_token_information.dex_id,
            )
        )

    if not unique_tokens:
        return []

    return fetch_dexscreener_token_information_list_sync(unique_tokens)


def is_address_in_open_positions(candidate_address: str, open_position_addresses: set[str]) -> bool:
    return bool(candidate_address) and candidate_address in open_position_addresses


def run_awaitable_in_fresh_loop(asynchronous_task: Awaitable[U], debug_label: str = "") -> U:
    try:
        return asyncio.run(asynchronous_task)
    except RuntimeError as runtime_exception:
        exception_message = str(runtime_exception)
        if ("Event loop is closed" not in exception_message) and ("cannot be called from a running event loop" not in exception_message):
            raise

        resolved_label = debug_label or "asynchronous_task"
        logger.exception("[TRADING][ASYNC] Event loop constraint detected for task %s with message: %s. Re-running in isolated thread.", resolved_label, exception_message)

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


def fetch_trading_candidates_sync() -> list[TradingCandidate]:
    from src.integrations.dexscreener.dexscreener_client import fetch_trending_candidates

    token_information_list: list[DexscreenerTokenInformation] = run_awaitable_in_fresh_loop(
        asynchronous_task=fetch_trending_candidates(),
        debug_label="fetch_trading_candidates",
    )
    candidates_list: list[TradingCandidate] = [candidate_from_dexscreener_token_information(token_information) for token_information in token_information_list]
    logger.info("[TRADING][FETCH] Successfully converted %d token records into trading candidates", len(candidates_list))
    return candidates_list
