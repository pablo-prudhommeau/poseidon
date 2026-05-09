from __future__ import annotations

import asyncio
import threading
from enum import Enum
from typing import Awaitable, Optional, TypeVar, Dict, Set, Any

from src.core.structures.structures import Token, BlockchainNetwork
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger
from src.persistence.models import TradingPosition

logger = get_application_logger(__name__)

U = TypeVar("U")

_NATIVE_SYMBOL_SYNONYMS: Dict[BlockchainNetwork, Set[str]] = {
    BlockchainNetwork.BASE: {"ETH", "WETH"},
    BlockchainNetwork.BSC: {"BNB", "WBNB"},
    BlockchainNetwork.AVALANCHE: {"AVAX", "WAVAX"},
    BlockchainNetwork.SOLANA: {"SOL", "WSOL"},
}


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


def convert_trading_position_to_token(position: TradingPosition) -> Token:
    pair_address: Optional[str] = position.pair_address if isinstance(position.pair_address,
                                                                      str) and position.pair_address else None
    return Token(
        chain=position.blockchain_network,
        token_address=position.token_address,
        symbol=position.token_symbol,
        pair_address=pair_address,
        dex_id=position.dex_id,
    )


def normalize_side_to_upper(value: str | Enum | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.upper()
    if isinstance(value, Enum):
        try:
            enum_value = value.value
        except Exception:
            enum_value = str(value)
        return str(enum_value).upper()
    return str(value).upper()


def get_symbol(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    sym = obj.get("symbol") or obj.get("sym") or obj.get("ticker")
    return str(sym).strip().upper() if isinstance(sym, str) else ""


def get_address(obj: Any) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    addr = obj.get("address") or obj.get("addr")
    return str(addr) if isinstance(addr, str) and addr else None


def native_synonyms(chain_key: BlockchainNetwork) -> Set[str]:
    return _NATIVE_SYMBOL_SYNONYMS.get(chain_key, {"ETH", "WETH"})


def is_native_symbol(symbol: str, chain_key: BlockchainNetwork) -> bool:
    return symbol.upper() in native_synonyms(chain_key)


def get_currency_symbol(asset_symbol: str) -> str:
    if not asset_symbol:
        return ""

    symbol_upper = asset_symbol.upper()

    if any(sub in symbol_upper for sub in ["USD", "DAI", "USDT", "USDC"]):
        return "$"
    if "EUR" in symbol_upper:
        return "€"
    if "BTC" in symbol_upper:
        return "₿"
    if "ETH" in symbol_upper:
        return "Ξ"
    if "SOL" in symbol_upper:
        return "◎"
    if "LINK" in symbol_upper:
        return "⬡"

    return asset_symbol
