from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, TypeVar, Optional

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.date_utils import get_current_local_datetime
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.core.trading.execution.trading_execution_structures import TradingLiveSellExecutionOutcome
from src.integrations.blockchain.blockchain_execution_structures import (
    BlockchainTransactionExecutionError,
    BlockchainTransactionFailureReason,
)
from src.integrations.blockchain.blockchain_live_executor import BlockchainExecutionResult, LiveExecutionService
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainExecutionRouteBuildError,
    BlockchainPriceUnavailableError,
    BlockchainRpcUnavailableError,
    is_transient_solana_rpc_failure,
)
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_price_for_token
from src.integrations.blockchain.blockchain_structures import (
    BlockchainExecutionRoute,
    BlockchainSolanaRoute,
)
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
from src.integrations.blockchain.solana.solana_onchain_wallet_context_service import (
    invalidate_solana_onchain_wallet_context_cache,
)
from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals
from src.integrations.blockchain.solana.solana_wallet_snapshot_service import (
    invalidate_solana_wallet_snapshot_cache,
    resolve_solana_wallet_snapshot,
)
from src.integrations.jupiter.jupiter_client import generate_jupiter_swap_transaction
from src.integrations.jupiter.jupiter_structures import JupiterApiFailureReason, JupiterApiUnavailableError
from src.core.trading.execution.trading_execution_structures import TradingPositionClosingSellResult
from src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service import (
    poll_deployable_stablecoin_until_swap_settled,
    resolve_total_deployable_stablecoin_cash_usd,
)
from src.core.trading.portfolio.trading_portfolio_structures import StablecoinSwapSettlementDirection
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import ExecutionStatus, TradingPosition, TradingTrade, TradeSide, PositionPhase

logger = get_application_logger(__name__)

T = TypeVar("T")


def build_solana_buy_route(candidate: TradingCandidate, order_notional_usd: float) -> BlockchainExecutionRoute:
    token_mint = (candidate.token.token_address or "").strip()
    if not token_mint:
        raise BlockchainExecutionRouteBuildError(
            f"Missing SPL token mint for {candidate.token.symbol}",
            blockchain_network=BlockchainNetwork.SOLANA,
        )

    stablecoin_address = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    if not stablecoin_address:
        raise BlockchainExecutionRouteBuildError(
            "Missing stablecoin address for Solana",
            blockchain_network=BlockchainNetwork.SOLANA,
        )

    from_amount_raw = _compute_from_amount_stablecoin_raw(order_notional_usd)
    if from_amount_raw is None:
        raise BlockchainExecutionRouteBuildError(
            f"Cannot compute stablecoin raw amount for {candidate.token.symbol}",
            blockchain_network=BlockchainNetwork.SOLANA,
        )

    try:
        from_address = build_default_solana_signer().address
    except Exception as exception:
        raise BlockchainExecutionRouteBuildError(
            f"Solana signer unavailable for {candidate.token.symbol}",
            blockchain_network=BlockchainNetwork.SOLANA,
        ) from exception

    slippage_basis_points = int(settings.TRADING_SLIPPAGE_TOLERANCE * 10000)
    try:
        base64_transaction = generate_jupiter_swap_transaction(
            source_address=from_address,
            input_mint=stablecoin_address,
            output_mint=token_mint,
            amount_in_lamports=from_amount_raw,
            slippage_basis_points=slippage_basis_points,
        )
    except JupiterApiUnavailableError as jupiter_unavailable_error:
        raise _build_solana_route_error_from_jupiter_unavailable(jupiter_unavailable_error) from jupiter_unavailable_error

    solana_route = BlockchainSolanaRoute(serialized_transaction_base64=base64_transaction)
    return BlockchainExecutionRoute(solana_route=solana_route)


def build_solana_sell_route(token_mint: str, token_quantity: float, token_decimals: int) -> BlockchainExecutionRoute:
    if not token_mint:
        raise BlockchainExecutionRouteBuildError(
            "Missing SPL token mint for sell route",
            blockchain_network=BlockchainNetwork.SOLANA,
        )

    amount_lamports = int(token_quantity * (10 ** token_decimals))
    if amount_lamports <= 0:
        raise BlockchainExecutionRouteBuildError(
            f"Non-positive sell amount for token mint {token_mint}",
            blockchain_network=BlockchainNetwork.SOLANA,
        )

    stablecoin_address = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    if not stablecoin_address:
        raise BlockchainExecutionRouteBuildError(
            "Missing stablecoin address for Solana sell route",
            blockchain_network=BlockchainNetwork.SOLANA,
        )

    try:
        from_address = build_default_solana_signer().address
    except Exception as exception:
        raise BlockchainExecutionRouteBuildError(
            f"Solana signer unavailable for sell route token mint {token_mint}",
            blockchain_network=BlockchainNetwork.SOLANA,
        ) from exception

    slippage_basis_points = int(settings.TRADING_SLIPPAGE_TOLERANCE * 10000)
    try:
        base64_transaction = generate_jupiter_swap_transaction(
            source_address=from_address,
            input_mint=token_mint,
            output_mint=stablecoin_address,
            amount_in_lamports=amount_lamports,
            slippage_basis_points=slippage_basis_points,
        )
    except JupiterApiUnavailableError as jupiter_unavailable_error:
        raise _build_solana_route_error_from_jupiter_unavailable(jupiter_unavailable_error) from jupiter_unavailable_error

    solana_route = BlockchainSolanaRoute(serialized_transaction_base64=base64_transaction)
    return BlockchainExecutionRoute(solana_route=solana_route)


def _build_solana_route_error_from_jupiter_unavailable(
        jupiter_unavailable_error: JupiterApiUnavailableError,
) -> BlockchainExecutionRouteBuildError:
    is_transient = jupiter_unavailable_error.failure_reason in {
        JupiterApiFailureReason.RATE_LIMITED,
        JupiterApiFailureReason.NETWORK_ERROR,
    }
    if is_transient:
        logger.debug(
            "[TRADING][EXECUTION][SOLANA][ROUTE] Jupiter unavailable — failure_reason=%s",
            jupiter_unavailable_error.failure_reason.value,
        )
    else:
        logger.warning(
            "[TRADING][EXECUTION][SOLANA][ROUTE] Jupiter unavailable — failure_reason=%s",
            jupiter_unavailable_error.failure_reason.value,
        )
    return BlockchainExecutionRouteBuildError(
        str(jupiter_unavailable_error),
        blockchain_network=BlockchainNetwork.SOLANA,
        is_transient=is_transient,
    )


def resolve_solana_sell_token_decimals(token_address: str) -> int:
    rpc_url = resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)
    return get_spl_token_decimals(rpc_url, token_address)


def cap_solana_sell_quantity_to_wallet_balance(
        token_address: str,
        sell_quantity: float,
        token_decimals: int,
) -> float:
    wallet_snapshot = resolve_solana_wallet_snapshot(force_refresh=True)
    token_account_balance_raw = 0
    for token_account in wallet_snapshot.token_accounts:
        if token_account.token_mint_address != token_address:
            continue
        token_account_balance_raw = token_account.balance_raw
        break

    actual_balance = float(token_account_balance_raw) / float(10 ** token_decimals)
    if actual_balance < sell_quantity:
        logger.warning(
            "[TRADING][EXECUTION][SOLANA][POSITION] Actual balance (%.6f) is less than theoretical (%.6f). Capping sell quantity.",
            actual_balance,
            sell_quantity,
        )
        return actual_balance
    return sell_quantity


def run_solana_live_buy_blocking(
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
        _execute_solana_live_buy(
            token=token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss_usd,
            take_profit_tp1_usd=take_profit_tp1_usd,
            take_profit_tp2_usd=take_profit_tp2_usd,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        ),
        debug_label="live-buy",
    )


def resolve_solana_wallet_token_transfer_blocked_for_mint(token_mint_address: str) -> bool:
    wallet_snapshot = resolve_solana_wallet_snapshot(force_refresh=False)
    for token_account in wallet_snapshot.token_accounts:
        if token_account.token_mint_address != token_mint_address:
            continue
        return token_account.account_state.strip().lower() == "frozen"
    return False


def run_solana_live_sell_blocking(
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
        _execute_solana_live_sell(
            token_symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            dex_id=dex_id,
            quantity=quantity,
            execution_price=execution_price,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        ),
        debug_label="live-sell",
    )


def _compute_from_amount_stablecoin_raw(order_notional_usd: float) -> Optional[int]:
    try:
        amount_raw = int(order_notional_usd * (10 ** 6))
        return amount_raw if amount_raw > 0 else None
    except Exception:
        return None


def _fetch_onchain_price_for_token(token: Token) -> Optional[float]:
    try:
        price_usd = fetch_onchain_price_for_token(token)
        if price_usd is not None and price_usd > 0.0:
            logger.debug("[TRADING][EXECUTION][SOLANA][PRICE] On-chain price fetched for %s = %.12f", token, price_usd)
            return price_usd

        logger.debug("[TRADING][EXECUTION][SOLANA][PRICE] No valid on-chain price for %s", token)
        return None
    except BlockchainPriceUnavailableError as price_unavailable_error:
        logger.warning("[TRADING][EXECUTION][SOLANA][PRICE] %s", price_unavailable_error)
        return None
    except Exception:
        logger.exception("[TRADING][EXECUTION][SOLANA][PRICE] On-chain price fetch failed for %s", token)
        return None


def _run_awaitable_blocking(awaitable: Awaitable[T], debug_label: str) -> T:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        logger.debug("[TRADING][EXECUTION][SOLANA][SWAP] Blocking execution via worker thread (%s)", debug_label)
        with ThreadPoolExecutor(max_workers=1) as thread_executor:
            future = thread_executor.submit(asyncio.run, awaitable)
            return future.result()

    logger.debug("[TRADING][EXECUTION][SOLANA][SWAP] Blocking execution via asyncio.run (%s)", debug_label)
    return asyncio.run(awaitable)


async def _execute_solana_live_buy(
        token: Token,
        quantity: float,
        price_usd: float,
        stop_loss_usd: float,
        take_profit_tp1_usd: float,
        take_profit_tp2_usd: float,
        execution_route: BlockchainExecutionRoute,
        origin_evaluation_id: int,
) -> bool:
    execution_service = LiveExecutionService()
    buy_committed = False
    try:
        logger.info(
            "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Executing route for %s on Solana",
            token.symbol,
        )

        jit_price_usd = await asyncio.to_thread(_fetch_onchain_price_for_token, token)
        if jit_price_usd is None or jit_price_usd <= 0.0:
            logger.warning("[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Skip JIT: Unable to fetch price right before execution. Aborting.")
            return False

        maximum_slippage = settings.TRADING_MAX_SLIPPAGE
        low_price, high_price = sorted([jit_price_usd, price_usd])
        if (high_price / low_price - 1.0) > maximum_slippage:
            logger.warning(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] JIT Slippage guard triggered for %s — intended=%.12f current=%.12f (>%.1f%%). Aborting cleanly.",
                token.symbol,
                price_usd,
                jit_price_usd,
                maximum_slippage * 100.0,
            )
            return False

        if execution_route.solana_route is None:
            logger.error("[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Missing Solana route payload for %s", token.symbol)
            return False

        try:
            deployable_cash_before_swap_usd = await asyncio.to_thread(resolve_total_deployable_stablecoin_cash_usd)
        except BlockchainRpcUnavailableError as rpc_unavailable_error:
            logger.debug(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Deployable baseline unavailable for %s — failure_reason=%s",
                token.symbol,
                rpc_unavailable_error.failure_reason.value,
            )
            return False

        execution_outcome = await execution_service.solana_execute_route(execution_route.solana_route)
        logger.info(
            "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Broadcast successful for %s — sig=%s fee_usd=%.6f",
            token.symbol,
            execution_outcome.transaction_hash_or_signature,
            execution_outcome.transaction_fee_usd,
        )

        settlement_poll_result = await asyncio.to_thread(
            poll_deployable_stablecoin_until_swap_settled,
            deployable_cash_before_swap_usd,
            StablecoinSwapSettlementDirection.BUY_DEBIT,
            execution_outcome.transaction_hash_or_signature,
        )
        if not settlement_poll_result.swap_settled_on_chain:
            logger.warning(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Stablecoin debit not reflected on-chain before ledger update — "
                "token=%s transaction_signature=%s deployable_before=%.2f last_observed_deployable=%.2f",
                token.symbol,
                execution_outcome.transaction_hash_or_signature,
                deployable_cash_before_swap_usd,
                settlement_poll_result.deployable_cash_usd,
            )
            return False

        with get_database_session() as database_session:
            trade_dao = TradingTradeDao(database_session)
            position_dao = TradingPositionDao(database_session)

            trading_trade = TradingTrade(
                evaluation_id=origin_evaluation_id,
                trade_side=TradeSide.BUY,
                token_symbol=token.symbol,
                blockchain_network=BlockchainNetwork.SOLANA.value,
                execution_price=price_usd,
                execution_quantity=quantity,
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
                blockchain_network=BlockchainNetwork.SOLANA.value,
                token_address=token.token_address,
                pair_address=token.pair_address,
                open_quantity=quantity,
                current_quantity=quantity,
                entry_price=price_usd,
                take_profit_tier_1_price=take_profit_tp1_usd,
                take_profit_tier_2_price=take_profit_tp2_usd,
                stop_loss_price=stop_loss_usd,
                position_phase=PositionPhase.OPEN,
                dex_id=token.dex_id,
                opened_at=get_current_local_datetime(),
                updated_at=get_current_local_datetime(),
            )
            position_dao.save(trading_position)

            database_session.commit()
        invalidate_solana_wallet_snapshot_cache()
        invalidate_solana_onchain_wallet_context_cache()
        buy_committed = True
        return True
    except BlockchainRpcUnavailableError as rpc_unavailable_error:
        if is_transient_solana_rpc_failure(rpc_unavailable_error):
            logger.debug(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Transient RPC unavailable for %s (%s) — failure_reason=%s rpc_method=%s",
                token.symbol,
                token.token_address,
                rpc_unavailable_error.failure_reason.value,
                rpc_unavailable_error.rpc_method,
            )
        else:
            logger.warning(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] RPC unavailable for %s (%s) — failure_reason=%s",
                token.symbol,
                token.token_address,
                rpc_unavailable_error.failure_reason.value,
            )
        return False
    except Exception as exception:
        logger.exception(
            "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][BUY] Execution failed for %s (%s) — %s",
            token.symbol,
            token.token_address,
            exception,
        )
        return False
    finally:
        try:
            await execution_service.close()
        except Exception as close_exception:
            logger.exception("[TRADING][EXECUTION][SOLANA][SWAP][LIVE] Execution service close suppressed — %s", close_exception)
        if buy_committed:
            cache_invalidator.mark_dirty(
                CacheRealm.POSITIONS,
                CacheRealm.TRADES,
                CacheRealm.AVAILABLE_CASH,
                CacheRealm.PORTFOLIO,
            )


async def _execute_solana_live_sell(
        token_symbol: str,
        token_address: str,
        pair_address: str,
        dex_id: str,
        quantity: float,
        execution_price: float,
        execution_route: BlockchainExecutionRoute,
        origin_evaluation_id: int,
) -> TradingLiveSellExecutionOutcome:
    execution_service = LiveExecutionService()
    try:
        logger.info(
            "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Executing route for %s on Solana",
            token_symbol,
        )

        temp_token = Token(
            symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            chain=BlockchainNetwork.SOLANA,
            dex_id=dex_id,
        )
        jit_price_usd = await asyncio.to_thread(_fetch_onchain_price_for_token, temp_token)
        if jit_price_usd is None or jit_price_usd <= 0.0:
            logger.warning("[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Skip JIT: Unable to fetch price right before execution. Aborting.")
            return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)

        maximum_slippage = settings.TRADING_MAX_SLIPPAGE
        low_price, high_price = sorted([jit_price_usd, execution_price])
        if (high_price / low_price - 1.0) > maximum_slippage:
            logger.warning(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] JIT Slippage guard triggered for %s — intended=%.12f current=%.12f (>%.1f%%). Aborting cleanly.",
                token_symbol,
                execution_price,
                jit_price_usd,
                maximum_slippage * 100.0,
            )
            return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)

        if execution_route.solana_route is None:
            logger.error("[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Missing Solana route payload for %s", token_symbol)
            return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)

        execution_outcome = await execution_service.solana_execute_route(execution_route.solana_route)
        logger.info(
            "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Broadcast successful for %s — sig=%s fee_usd=%.6f",
            token_symbol,
            execution_outcome.transaction_hash_or_signature,
            execution_outcome.transaction_fee_usd,
        )
        invalidate_solana_wallet_snapshot_cache()
        invalidate_solana_onchain_wallet_context_cache()
        return TradingLiveSellExecutionOutcome(execution_result=execution_outcome, failure_reason=None)

    except BlockchainTransactionExecutionError as execution_error:
        if execution_error.failure_reason == BlockchainTransactionFailureReason.UNKNOWN:
            logger.warning(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Execution failed for %s (%s) — failure_reason=%s signature=%s error=%s",
                token_symbol,
                token_address,
                execution_error.failure_reason.value,
                execution_error.transaction_signature,
                execution_error.raw_error_text,
            )
        else:
            logger.error(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Execution failed for %s (%s) — failure_reason=%s signature=%s error=%s",
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
    except BlockchainRpcUnavailableError as rpc_unavailable_error:
        if is_transient_solana_rpc_failure(rpc_unavailable_error):
            logger.debug(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Transient RPC unavailable for %s (%s) — failure_reason=%s rpc_method=%s",
                token_symbol,
                token_address,
                rpc_unavailable_error.failure_reason.value,
                rpc_unavailable_error.rpc_method,
            )
        else:
            logger.warning(
                "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] RPC unavailable for %s (%s) — failure_reason=%s",
                token_symbol,
                token_address,
                rpc_unavailable_error.failure_reason.value,
            )
        return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)
    except Exception as exception:
        logger.exception(
            "[TRADING][EXECUTION][SOLANA][SWAP][LIVE][SELL] Execution failed for %s (%s) — %s",
            token_symbol,
            token_address,
            exception,
        )
        return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)
    finally:
        try:
            await execution_service.close()
        except Exception as close_exception:
            logger.exception("[TRADING][EXECUTION][SOLANA][SWAP][LIVE] Execution service close suppressed — %s", close_exception)
