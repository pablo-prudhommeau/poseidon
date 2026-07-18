from __future__ import annotations

import asyncio
import threading
from enum import Enum
from typing import Awaitable, Optional, TypeVar, Dict, Set, Any

from src.core.structures.structures import Token, BlockchainNetwork
from src.core.trading.screener.trading_screener_provider import get_trading_screener_provider
from src.core.trading.trading_structures import TradingCandidate
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


def refresh_candidates_from_screener(candidates: list[TradingCandidate]) -> None:
    get_trading_screener_provider().refresh_candidates(candidates)


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


def resolve_spendable_cash_usd(available_cash_usd: float) -> float:
    return max(0.0, available_cash_usd)


def is_buy_notional_executable(
        order_notional_usd: float,
        available_cash_usd: float,
) -> bool:
    if order_notional_usd <= 0.0:
        return False
    return order_notional_usd <= resolve_spendable_cash_usd(available_cash_usd)
