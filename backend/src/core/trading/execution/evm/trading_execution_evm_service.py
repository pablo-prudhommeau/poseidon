from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Optional, TypeVar

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.execution.trading_execution_structures import TradingLiveSellExecutionOutcome
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainExecutionRouteBuildError,
    BlockchainPriceUnavailableError,
)
from src.integrations.blockchain.blockchain_execution_service import BlockchainExecutionService
from src.integrations.blockchain.blockchain_execution_structures import (
    BlockchainTransactionExecutionError,
)
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_price_for_token
from src.integrations.blockchain.blockchain_structures import (
    BlockchainEvmRoute,
    BlockchainExecutionRoute,
)
from src.integrations.blockchain.evm.blockchain_evm_erc20_helpers import (
    ensure_evm_erc20_allowance_for_lifi_diamond,
    resolve_evm_erc20_balance_raw,
    resolve_evm_erc20_decimals,
)
from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer
from src.integrations.lifi.lifi_client import generate_token_to_token_route
from src.integrations.lifi.lifi_structures import LifiQuoteUnavailableError, LifiRouteNormalizationError
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import ExecutionStatus, PositionPhase, TradeSide, TradingPosition, TradingTrade

logger = get_application_logger(__name__)

T = TypeVar("T")


def build_evm_buy_route(
        blockchain_network: BlockchainNetwork,
        candidate: TradingCandidate,
        order_notional_usd: float,
) -> BlockchainExecutionRoute:
    token_address = (candidate.token.token_address or "").strip()
    if not token_address:
        raise BlockchainExecutionRouteBuildError(
            f"Missing ERC20 token address for {candidate.token.symbol}",
            blockchain_network=blockchain_network,
        )

    stablecoin_address = resolve_stablecoin_address_for_blockchain(blockchain_network)
    if not stablecoin_address:
        raise BlockchainExecutionRouteBuildError(
            f"Missing stablecoin address for {blockchain_network.value}",
            blockchain_network=blockchain_network,
        )

    try:
        wallet_address = build_default_evm_signer(blockchain_network).wallet_address
        stablecoin_decimals = resolve_evm_erc20_decimals(blockchain_network, stablecoin_address)
    except Exception as exception:
        raise BlockchainExecutionRouteBuildError(
            f"EVM signer or stablecoin decimals unavailable for {candidate.token.symbol}",
            blockchain_network=blockchain_network,
        ) from exception

    source_amount_wei = int(order_notional_usd * (10**stablecoin_decimals))
    if source_amount_wei <= 0:
        raise BlockchainExecutionRouteBuildError(
            f"Cannot compute stablecoin wei amount for {candidate.token.symbol}",
            blockchain_network=blockchain_network,
        )

    try:
        lifi_route = generate_token_to_token_route(
            chain=blockchain_network,
            source_address=wallet_address,
            source_token_address=stablecoin_address,
            destination_token_address=token_address,
            source_amount_wei=source_amount_wei,
            slippage_tolerance=settings.TRADING_SLIPPAGE_TOLERANCE,
        )
    except (LifiQuoteUnavailableError, LifiRouteNormalizationError, ValueError, RuntimeError) as exception:
        raise BlockchainExecutionRouteBuildError(
            str(exception),
            blockchain_network=blockchain_network,
            is_transient=isinstance(exception, LifiQuoteUnavailableError),
        ) from exception

    if lifi_route.transaction_request is None:
        raise BlockchainExecutionRouteBuildError(
            f"LiFi buy route missing transaction request for {candidate.token.symbol}",
            blockchain_network=blockchain_network,
        )

    return BlockchainExecutionRoute(
        evm_route=BlockchainEvmRoute(
            transaction_request=lifi_route.transaction_request,
            approval_token_address=stablecoin_address,
            approval_required_amount_wei=source_amount_wei,
        ),
    )


def build_evm_sell_route(
        blockchain_network: BlockchainNetwork,
        token_address: str,
        token_quantity: float,
        token_decimals: int,
) -> BlockchainExecutionRoute:
    if not token_address.strip():
        raise BlockchainExecutionRouteBuildError(
            "Missing ERC20 token address for sell route",
            blockchain_network=blockchain_network,
        )

    token_amount_wei = int(token_quantity * (10**token_decimals))
    if token_amount_wei <= 0:
        raise BlockchainExecutionRouteBuildError(
            f"Non-positive sell amount for token {token_address}",
            blockchain_network=blockchain_network,
        )

    stablecoin_address = resolve_stablecoin_address_for_blockchain(blockchain_network)
    if not stablecoin_address:
        raise BlockchainExecutionRouteBuildError(
            f"Missing stablecoin address for {blockchain_network.value} sell route",
            blockchain_network=blockchain_network,
        )

    try:
        wallet_address = build_default_evm_signer(blockchain_network).wallet_address
        lifi_route = generate_token_to_token_route(
            chain=blockchain_network,
            source_address=wallet_address,
            source_token_address=token_address,
            destination_token_address=stablecoin_address,
            source_amount_wei=token_amount_wei,
            slippage_tolerance=settings.TRADING_SLIPPAGE_TOLERANCE,
        )
    except (LifiQuoteUnavailableError, LifiRouteNormalizationError, ValueError, RuntimeError) as exception:
        raise BlockchainExecutionRouteBuildError(
            str(exception),
            blockchain_network=blockchain_network,
            is_transient=isinstance(exception, LifiQuoteUnavailableError),
        ) from exception

    if lifi_route.transaction_request is None:
        raise BlockchainExecutionRouteBuildError(
            f"LiFi sell route missing transaction request for token {token_address}",
            blockchain_network=blockchain_network,
        )

    return BlockchainExecutionRoute(
        evm_route=BlockchainEvmRoute(
            transaction_request=lifi_route.transaction_request,
            approval_token_address=token_address,
            approval_required_amount_wei=token_amount_wei,
        ),
    )


def resolve_evm_sell_token_decimals(blockchain_network: BlockchainNetwork, token_address: str) -> int:
    return resolve_evm_erc20_decimals(blockchain_network, token_address)


def cap_evm_sell_quantity_to_wallet_balance(
        blockchain_network: BlockchainNetwork,
        token_address: str,
        sell_quantity: float,
        token_decimals: int,
) -> float:
    wallet_balance_raw = resolve_evm_erc20_balance_raw(blockchain_network, token_address)
    actual_balance = float(wallet_balance_raw) / float(10**token_decimals)
    if actual_balance < sell_quantity:
        logger.warning(
            "[TRADING][EXECUTION][EVM][POSITION] Actual balance (%.6f) is less than theoretical (%.6f). Capping sell quantity.",
            actual_balance,
            sell_quantity,
        )
        return actual_balance
    return sell_quantity


def run_evm_live_buy_blocking(
        blockchain_network: BlockchainNetwork,
        token: Token,
        quantity: float,
        price_usd: float,
        stop_loss_usd: float,
        take_profit_tp1_usd: float,
        take_profit_tp2_usd: float,
        execution_route: BlockchainExecutionRoute,
        origin_evaluation_id: int,
) -> bool:
    return _run_awaitable_blocking(
        _execute_evm_live_buy(
            blockchain_network=blockchain_network,
            token=token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss_usd,
            take_profit_tp1_usd=take_profit_tp1_usd,
            take_profit_tp2_usd=take_profit_tp2_usd,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        ),
        debug_label="evm-live-buy",
    )


def run_evm_live_sell_blocking(
        blockchain_network: BlockchainNetwork,
        token_symbol: str,
        token_address: str,
        pair_address: str,
        dex_id: str,
        quantity: float,
        execution_price: float,
        execution_route: BlockchainExecutionRoute,
        origin_evaluation_id: int,
) -> TradingLiveSellExecutionOutcome:
    return _run_awaitable_blocking(
        _execute_evm_live_sell(
            blockchain_network=blockchain_network,
            token_symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            dex_id=dex_id,
            quantity=quantity,
            execution_price=execution_price,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        ),
        debug_label="evm-live-sell",
    )


def _fetch_price_for_token(token: Token) -> Optional[float]:
    try:
        price_usd = fetch_onchain_price_for_token(token)
        if price_usd is not None and price_usd > 0.0:
            return price_usd
        return None
    except BlockchainPriceUnavailableError as price_unavailable_error:
        logger.warning("[TRADING][EXECUTION][EVM][PRICE] %s", price_unavailable_error)
        return None
    except Exception:
        logger.exception("[TRADING][EXECUTION][EVM][PRICE] Price fetch failed for %s", token)
        return None


def _run_awaitable_blocking(awaitable: Awaitable[T], debug_label: str) -> T:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        logger.debug("[TRADING][EXECUTION][EVM][SWAP] Blocking execution via worker thread (%s)", debug_label)
        with ThreadPoolExecutor(max_workers=1) as thread_executor:
            future = thread_executor.submit(asyncio.run, awaitable)
            return future.result()

    return asyncio.run(awaitable)


async def _execute_evm_live_buy(
        blockchain_network: BlockchainNetwork,
        token: Token,
        quantity: float,
        price_usd: float,
        stop_loss_usd: float,
        take_profit_tp1_usd: float,
        take_profit_tp2_usd: float,
        execution_route: BlockchainExecutionRoute,
        origin_evaluation_id: int,
) -> bool:
    execution_service = BlockchainExecutionService()
    buy_committed = False
    try:
        logger.info(
            "[TRADING][EXECUTION][EVM][SWAP][LIVE][BUY] Executing route for %s on %s",
            token.symbol,
            blockchain_network.value,
        )

        jit_price_usd = await asyncio.to_thread(_fetch_price_for_token, token)
        if jit_price_usd is None or jit_price_usd <= 0.0:
            logger.warning(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE][BUY] Skip JIT: Unable to fetch price right before execution. Aborting.",
            )
            return False

        maximum_slippage = settings.TRADING_MAX_SLIPPAGE
        low_price, high_price = sorted([jit_price_usd, price_usd])
        if (high_price / low_price - 1.0) > maximum_slippage:
            logger.warning(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE][BUY] JIT Slippage guard triggered for %s — intended=%.12f current=%.12f (>%.1f%%). Aborting cleanly.",
                token.symbol,
                price_usd,
                jit_price_usd,
                maximum_slippage * 100.0,
            )
            return False

        if execution_route.evm_route is None:
            logger.error(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE][BUY] Missing EVM route payload for %s",
                token.symbol,
            )
            return False

        await asyncio.to_thread(_ensure_evm_route_allowance, blockchain_network, execution_route.evm_route)

        execution_outcome = await execution_service.evm_execute_route(
            route=execution_route.evm_route,
            chain=blockchain_network,
        )
        logger.info(
            "[TRADING][EXECUTION][EVM][SWAP][LIVE][BUY] Broadcast successful for %s — hash=%s fee_usd=%.6f",
            token.symbol,
            execution_outcome.transaction_hash_or_signature,
            execution_outcome.transaction_fee_usd,
        )

        recorded_price_usd = price_usd
        recorded_quantity = quantity
        take_profit_one_fraction = settings.TRADING_BREAKEVEN_ARM_FRACTION
        take_profit_two_fraction = settings.TRADING_TAKE_PROFIT_EXIT_FRACTION
        stop_loss_fraction = settings.TRADING_STOP_LOSS_FRACTION
        take_profit_tp1_usd = recorded_price_usd * (1.0 + take_profit_one_fraction)
        take_profit_tp2_usd = recorded_price_usd * (1.0 + take_profit_two_fraction)
        stop_loss_usd = recorded_price_usd * (1.0 - stop_loss_fraction)

        with get_database_session() as database_session:
            trade_dao = TradingTradeDao(database_session)
            position_dao = TradingPositionDao(database_session)

            trading_trade = TradingTrade(
                evaluation_id=origin_evaluation_id,
                trade_side=TradeSide.BUY,
                token_symbol=token.symbol,
                blockchain_network=blockchain_network.value,
                execution_price=recorded_price_usd,
                execution_quantity=recorded_quantity,
                transaction_fee=execution_outcome.transaction_fee_usd,
                realized_profit_and_loss=None,
                execution_status=ExecutionStatus.LIVE,
                token_address=token.token_address,
                pair_address=token.pair_address,
                dex_id=token.dex_id,
                transaction_hash=execution_outcome.transaction_hash_or_signature,
                created_at=get_current_local_datetime(),
            )
            trade_dao.save(trading_trade)

            trading_position = TradingPosition(
                evaluation_id=origin_evaluation_id,
                token_symbol=token.symbol,
                blockchain_network=blockchain_network.value,
                token_address=token.token_address,
                pair_address=token.pair_address,
                open_quantity=recorded_quantity,
                current_quantity=recorded_quantity,
                entry_price=recorded_price_usd,
                breakeven_arm_price=take_profit_tp1_usd,
                take_profit_price=take_profit_tp2_usd,
                stop_loss_price=stop_loss_usd,
                initial_stop_loss_price=stop_loss_usd,
                position_phase=PositionPhase.OPEN,
                dex_id=token.dex_id,
                opened_at=get_current_local_datetime(),
                updated_at=get_current_local_datetime(),
            )
            position_dao.save(trading_position)
            database_session.commit()

        buy_committed = True
        return True
    except Exception as exception:
        logger.exception(
            "[TRADING][EXECUTION][EVM][SWAP][LIVE][BUY] Execution failed for %s (%s) — %s",
            token.symbol,
            token.token_address,
            exception,
        )
        return False
    finally:
        try:
            await execution_service.close()
        except Exception as close_exception:
            logger.exception(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE] Execution service close suppressed — %s",
                close_exception,
            )
        if buy_committed:
            cache_invalidator.mark_dirty(
                CacheRealm.POSITIONS,
                CacheRealm.TRADES,
                CacheRealm.AVAILABLE_CASH,
                CacheRealm.PORTFOLIO,
            )


def _ensure_evm_route_allowance(
        blockchain_network: BlockchainNetwork,
        evm_route: BlockchainEvmRoute,
) -> None:
    if not evm_route.approval_token_address or evm_route.approval_required_amount_wei <= 0:
        return
    ensure_evm_erc20_allowance_for_lifi_diamond(
        blockchain_network=blockchain_network,
        token_address=evm_route.approval_token_address,
        required_amount_wei=evm_route.approval_required_amount_wei,
    )


async def _execute_evm_live_sell(
        blockchain_network: BlockchainNetwork,
        token_symbol: str,
        token_address: str,
        pair_address: str,
        dex_id: str,
        quantity: float,
        execution_price: float,
        execution_route: BlockchainExecutionRoute,
        origin_evaluation_id: int,
) -> TradingLiveSellExecutionOutcome:
    execution_service = BlockchainExecutionService()
    try:
        logger.info(
            "[TRADING][EXECUTION][EVM][SWAP][LIVE][SELL] Executing route for %s on %s",
            token_symbol,
            blockchain_network.value,
        )

        jit_token = Token(
            symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            chain=blockchain_network,
            dex_id=dex_id,
        )
        jit_price_usd = await asyncio.to_thread(_fetch_price_for_token, jit_token)
        if jit_price_usd is None or jit_price_usd <= 0.0:
            logger.warning(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE][SELL] Skip JIT: Unable to fetch price right before execution. Aborting.",
            )
            return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)

        maximum_slippage = settings.TRADING_MAX_SLIPPAGE
        low_price, high_price = sorted([jit_price_usd, execution_price])
        if (high_price / low_price - 1.0) > maximum_slippage:
            logger.warning(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE][SELL] JIT Slippage guard triggered for %s — intended=%.12f current=%.12f (>%.1f%%). Aborting cleanly.",
                token_symbol,
                execution_price,
                jit_price_usd,
                maximum_slippage * 100.0,
            )
            return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)

        if execution_route.evm_route is None:
            logger.error(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE][SELL] Missing EVM route payload for %s",
                token_symbol,
            )
            return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)

        await asyncio.to_thread(_ensure_evm_route_allowance, blockchain_network, execution_route.evm_route)

        execution_outcome = await execution_service.evm_execute_route(
            route=execution_route.evm_route,
            chain=blockchain_network,
        )
        logger.info(
            "[TRADING][EXECUTION][EVM][SWAP][LIVE][SELL] Broadcast successful for %s — hash=%s fee_usd=%.6f",
            token_symbol,
            execution_outcome.transaction_hash_or_signature,
            execution_outcome.transaction_fee_usd,
        )
        return TradingLiveSellExecutionOutcome(execution_result=execution_outcome, failure_reason=None)
    except BlockchainTransactionExecutionError as execution_error:
        logger.error(
            "[TRADING][EXECUTION][EVM][SWAP][LIVE][SELL] Execution failed for %s (%s) — failure_reason=%s hash=%s error=%s",
            token_symbol,
            token_address,
            execution_error.failure_reason.value,
            execution_error.transaction_signature,
            execution_error.raw_error_text,
        )
        return TradingLiveSellExecutionOutcome(
            execution_result=None,
            failure_reason=execution_error.failure_reason,
        )
    except Exception as exception:
        logger.exception(
            "[TRADING][EXECUTION][EVM][SWAP][LIVE][SELL] Execution failed for %s (%s) — %s",
            token_symbol,
            token_address,
            exception,
        )
        return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)
    finally:
        try:
            await execution_service.close()
        except Exception as close_exception:
            logger.exception(
                "[TRADING][EXECUTION][EVM][SWAP][LIVE] Execution service close suppressed — %s",
                close_exception,
            )
