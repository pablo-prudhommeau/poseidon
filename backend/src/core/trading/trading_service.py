from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, List, Dict, Deque, Optional

from sqlalchemy.orm import Session

from src.api.http.api_schemas import TradingTradePayload
from src.configuration.config import _to_dict, settings
from src.core.structures.structures import RealizedProfitAndLoss, Token, CashFromTrades
from src.core.trading.cache.trading_cache import trading_cache
from src.core.trading.shadowing.cache.trading_shadowing_cache import trading_shadowing_cache
from src.core.trading.trading_structures import InventoryLot, TradingCandidate
from src.core.trading.trading_utils import normalize_side_to_upper, run_awaitable_in_fresh_loop, candidate_from_dexscreener_token_information
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime, parse_iso_datetime_to_local
from src.core.utils.math_utils import quantize_2dp, decimal_from_primitive
from src.integrations.blockchain.blockchain_free_cash_service import fetch_stablecoin_balances_for_allowed_chains
from src.integrations.dexscreener.dexscreener_client import fetch_trending_candidates
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_evaluation_dao import TradingEvaluationDao
from src.persistence.dao.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_trade_dao import TradingTradeDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import PositionPhase
from src.persistence.models import TradingEvaluation
from src.persistence.models import TradingTrade

logger = get_application_logger(__name__)


def compute_realized_profit_and_loss(trades: Iterable[TradingTradePayload], *, cutoff_hours: int = 24) -> RealizedProfitAndLoss:
    cutoff_timestamp = get_current_local_datetime() - timedelta(hours=cutoff_hours)

    def trade_timestamp(trade: TradingTradePayload) -> datetime:
        return parse_iso_datetime_to_local(trade.created_at)

    sorted_trades: List[TradingTradePayload] = sorted(trades, key=trade_timestamp)

    lots_by_token: Dict[Token, Deque[InventoryLot]] = defaultdict(deque)
    realized_total: Decimal = Decimal("0")
    realized_recent: Decimal = Decimal("0")

    for trade in sorted_trades:
        side = normalize_side_to_upper(trade.trade_side)
        token = Token(
            symbol=trade.token_symbol,
            chain=trade.blockchain_network,
            token_address=trade.token_address,
            pair_address=trade.pair_address,
            dex_id=trade.dex_id,
        )

        try:
            quantity = float(trade.execution_quantity) if trade.execution_quantity is not None else 0.0
            unit_price_usd = float(trade.execution_price) if trade.execution_price is not None else 0.0
            fee_usd = float(trade.transaction_fee) if trade.transaction_fee is not None else 0.0
        except (TypeError, ValueError):
            logger.debug("[PNL][REALIZED][SKIP] token=%s reason=invalid_numeric_fields", token)
            continue

        if quantity <= 0.0 or unit_price_usd <= 0.0:
            logger.debug("[PNL][REALIZED][SKIP] token=%s reason=non_positive_qty_or_price", token)
            continue

        if side == "BUY":
            buy_fee_per_unit_usd = fee_usd / quantity if quantity > 0.0 else 0.0
            lots_by_token[token].append(
                InventoryLot(quantity=quantity, unit_price_usd=unit_price_usd,
                             buy_fee_per_unit_usd=buy_fee_per_unit_usd)
            )
            continue

        if side == "SELL" and trade.realized_profit_and_loss is not None:
            is_recent = trade_timestamp(trade) >= cutoff_timestamp
            usd_contribution = decimal_from_primitive(trade.realized_profit_and_loss)
            realized_total += usd_contribution
            if is_recent:
                realized_recent += usd_contribution
            remaining_to_match = quantity
            while remaining_to_match > 1e-12 and lots_by_token[token]:
                lot = lots_by_token[token][0]
                matched_quantity = min(remaining_to_match, lot.quantity)
                lot.quantity -= matched_quantity
                remaining_to_match -= matched_quantity
                if lot.quantity <= 1e-12:
                    lots_by_token[token].popleft()
            continue

        if side == "SELL":
            sell_fee_per_unit_usd = fee_usd / quantity if quantity > 0.0 else 0.0
            remaining_to_match = quantity
            is_recent = trade_timestamp(trade) >= cutoff_timestamp

            while remaining_to_match > 1e-12 and lots_by_token[token]:
                lot = lots_by_token[token][0]
                matched_quantity = min(remaining_to_match, lot.quantity)

                pnl_per_unit = unit_price_usd - lot.unit_price_usd - lot.buy_fee_per_unit_usd - sell_fee_per_unit_usd
                pnl_contribution = decimal_from_primitive(matched_quantity) * decimal_from_primitive(pnl_per_unit)

                realized_total += pnl_contribution
                if is_recent:
                    realized_recent += pnl_contribution

                lot.quantity -= matched_quantity
                remaining_to_match -= matched_quantity
                if lot.quantity <= 1e-12:
                    lots_by_token[token].popleft()

    realized = RealizedProfitAndLoss(
        total_realized_profit_and_loss=float(quantize_2dp(realized_total)),
        recent_realized_profit_and_loss=float(quantize_2dp(realized_recent)),
    )

    return realized


def compute_available_cash_usd(*, database_session: Optional[Session] = None) -> float:
    if settings.PAPER_MODE:
        if database_session is not None:
            return compute_trade_ledger_available_cash_usd(database_session)
        with get_database_session() as opened_database_session:
            return compute_trade_ledger_available_cash_usd(opened_database_session)
    return _compute_live_available_cash_usd()


def compute_trade_ledger_available_cash_usd(database_session: Session) -> float:
    baseline_cash_usd = _resolve_trade_ledger_baseline_cash_usd(database_session)
    trade_records = _retrieve_trades_for_trade_ledger(database_session)
    cash_state = compute_cash_from_trades(baseline_cash_usd, trade_records)
    operating_mode_label = "paper" if settings.PAPER_MODE else "live"
    logger.debug(
        "[TRADING][CASH][LEDGER] Trade-ledger available cash resolved — mode=%s balance=%.2f",
        operating_mode_label,
        cash_state.available_cash,
    )
    return cash_state.available_cash


def has_any_closing_positions(database_session: Session) -> bool:
    closing_positions = TradingPositionDao(database_session).retrieve_by_phase(PositionPhase.CLOSING)
    return len(closing_positions) > 0


def compute_cash_from_trades(start_cash_usd: float, trades: Iterable[TradingTrade]) -> CashFromTrades:
    sorted_trades: List[TradingTrade] = list(trades)

    total_buys: Decimal = Decimal("0")
    total_sells: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")

    for trade in sorted_trades:
        side = normalize_side_to_upper(trade.trade_side)

        try:
            quantity = float(trade.execution_quantity) if trade.execution_quantity is not None else 0.0
            unit_price_usd = float(trade.execution_price) if trade.execution_price is not None else 0.0
            fee_usd_dec = decimal_from_primitive(trade.transaction_fee)
        except (TypeError, ValueError):
            logger.debug("[PNL][CASH][SKIP] reason=invalid_numeric_fields")
            continue

        if quantity <= 0.0 or unit_price_usd <= 0.0:
            logger.debug("[PNL][CASH][SKIP] reason=non_positive_qty_or_price")
            continue

        notional_dec = decimal_from_primitive(unit_price_usd * quantity)
        if side == "BUY":
            total_buys += notional_dec
        elif side == "SELL":
            total_sells += notional_dec
        total_fees += fee_usd_dec

    ending_cash = decimal_from_primitive(start_cash_usd) - total_buys + total_sells - total_fees
    result = CashFromTrades(
        available_cash=float(quantize_2dp(ending_cash)),
        total_buy_volume=float(quantize_2dp(total_buys)),
        total_sell_volume=float(quantize_2dp(total_sells)),
        total_fees_paid=float(quantize_2dp(total_fees)),
    )
    return result


def fetch_trading_candidates_sync() -> list[TradingCandidate]:
    token_information_list: list[DexscreenerTokenInformation] = run_awaitable_in_fresh_loop(
        asynchronous_task=fetch_trending_candidates(),
        debug_label="fetch_trading_candidates",
    )
    candidates_list: list[TradingCandidate] = [candidate_from_dexscreener_token_information(token_information) for token_information in token_information_list]
    logger.info("[TRADING][FETCH] Successfully converted %d token records into trading candidates", len(candidates_list))
    return candidates_list


def record_trading_evaluation(
        candidate: TradingCandidate,
        rank: int,
        decision: str,
        reason: str,
        sizing_multiplier: float = 0.0,
        order_notional_usd: float = 0.0,
        free_cash_before_usd: float = 0.0,
        free_cash_after_usd: float = 0.0,
) -> Optional[int]:
    token_information = candidate.dexscreener_token_information
    base_token = token_information.base_token

    volume = token_information.volume
    liquidity = token_information.liquidity
    price_change = token_information.price_change
    transactions = token_information.transactions

    computed_buy_to_sell_ratio = 0.5
    if transactions and (transactions.h1 or transactions.h24):
        reference_bucket = transactions.h1 if transactions.h1 else transactions.h24
        total_transaction_count = reference_bucket.buys + reference_bucket.sells
        if total_transaction_count > 0:
            computed_buy_to_sell_ratio = reference_bucket.buys / total_transaction_count

    cached_shadowing_regime = trading_shadowing_cache.get_trading_shadowing_regime_state()

    trading_evaluation = TradingEvaluation(
        token_symbol=base_token.symbol.upper(),
        blockchain_network=token_information.chain_id.value,
        token_address=str(base_token.address),
        pair_address=str(token_information.pair_address),
        price_usd=token_information.price_usd or 0.0,
        price_native=token_information.price_native or 0.0,
        candidate_rank=rank,
        quality_score=candidate.quality_score,
        ai_adjusted_quality_score=candidate.ai_adjusted_quality_score,
        ai_probability_take_profit_before_stop_loss=candidate.ai_buy_probability,
        ai_quality_score_delta=candidate.ai_quality_delta,
        token_age_hours=token_information.age_hours,
        volume_m5_usd=volume.m5 if volume and volume.m5 is not None else 0.0,
        volume_h1_usd=volume.h1 if volume and volume.h1 is not None else 0.0,
        volume_h6_usd=volume.h6 if volume and volume.h6 is not None else 0.0,
        volume_h24_usd=volume.h24 if volume and volume.h24 is not None else 0.0,
        liquidity_usd=liquidity.usd if liquidity and liquidity.usd is not None else 0.0,
        price_change_percentage_m5=price_change.m5 if price_change and price_change.m5 is not None else 0.0,
        price_change_percentage_h1=price_change.h1 if price_change and price_change.h1 is not None else 0.0,
        price_change_percentage_h6=price_change.h6 if price_change and price_change.h6 is not None else 0.0,
        price_change_percentage_h24=price_change.h24 if price_change and price_change.h24 is not None else 0.0,
        transaction_count_m5=transactions.m5.total_transactions if transactions and transactions.m5 else 0,
        transaction_count_h1=transactions.h1.total_transactions if transactions and transactions.h1 else 0,
        transaction_count_h6=transactions.h6.total_transactions if transactions and transactions.h6 else 0,
        transaction_count_h24=transactions.h24.total_transactions if transactions and transactions.h24 else 0,
        buy_to_sell_ratio=computed_buy_to_sell_ratio,
        market_cap_usd=token_information.market_cap or 0.0,
        fully_diluted_valuation_usd=token_information.fully_diluted_valuation or 0.0,
        dexscreener_boost=token_information.boost or 0.0,
        evaluated_at=get_current_local_datetime(),
        execution_decision=decision.upper(),
        sizing_multiplier=sizing_multiplier or 0.0,
        order_notional_value_usd=order_notional_usd or 0.0,
        free_cash_before_execution_usd=free_cash_before_usd or 0.0,
        free_cash_after_execution_usd=free_cash_after_usd or 0.0,
        shadowing_regime=(
            cached_shadowing_regime.model_dump(mode="json", exclude_none=True)
            if cached_shadowing_regime is not None and settings.TRADING_SHADOWING_ENABLED
            else None
        ),
        shadowing_metrics=(
            [metric.model_dump(mode="json") for metric in candidate.shadowing_diagnostics.evaluated_metrics]
            if candidate.shadowing_diagnostics.evaluated_metrics and settings.TRADING_SHADOWING_ENABLED
            else None
        ),
        cortex_inference_summary=(
            candidate.trading_cortex_inference_snapshot.model_dump(mode="json")
            if candidate.trading_cortex_inference_snapshot is not None
               and candidate.trading_cortex_inference_snapshot.model_ready
            else None
        ),
        raw_dexscreener_payload=candidate.dexscreener_token_information.model_dump(mode="json"),
        raw_configuration_settings=_to_dict(settings),
    )

    logger.info(
        "[TRADING][EVALUATION] Token %s evaluated -> Decision: %s | Reason: %s",
        trading_evaluation.token_symbol,
        decision.upper(),
        reason,
    )

    if decision.upper() != "BUY":
        return None

    with get_database_session() as database_session:
        serialized_evaluation = TradingEvaluationDao(database_session).record_evaluation(trading_evaluation)
        database_session.commit()
        return serialized_evaluation.id


def record_skipped_trading_evaluation(evaluation_candidate: TradingCandidate, sequence_rank: int, exclusion_reason: str) -> None:
    record_trading_evaluation(evaluation_candidate, rank=sequence_rank, decision="SKIP", reason=exclusion_reason)


def _resolve_trade_ledger_baseline_cash_usd(database_session: Session) -> float:
    if settings.PAPER_MODE:
        return settings.PAPER_STARTING_CASH
    return _resolve_live_trade_ledger_baseline_cash_usd(database_session)


def _resolve_live_trade_ledger_baseline_cash_usd(database_session: Session) -> float:
    portfolio_dao = TradingPortfolioSnapshotDao(database_session)
    latest_portfolio_snapshot = portfolio_dao.retrieve_latest_snapshot()
    if latest_portfolio_snapshot is not None:
        return latest_portfolio_snapshot.available_cash_balance

    logger.info(
        "[TRADING][CASH][LEDGER] No portfolio snapshot in live mode; "
        "bootstrapping trade-ledger baseline from on-chain balances"
    )
    on_chain_cash_balance_usd = _compute_live_available_cash_usd()
    trade_dao = TradingTradeDao(database_session)
    all_trade_records = trade_dao.retrieve_recent_trades(limit_count=100000)
    cash_state_from_zero_baseline = compute_cash_from_trades(0.0, all_trade_records)
    return on_chain_cash_balance_usd - cash_state_from_zero_baseline.available_cash


def _retrieve_trades_for_trade_ledger(database_session: Session) -> List[TradingTrade]:
    trade_dao = TradingTradeDao(database_session)
    all_trade_records = trade_dao.retrieve_recent_trades(limit_count=100000)

    if settings.PAPER_MODE:
        return all_trade_records

    portfolio_dao = TradingPortfolioSnapshotDao(database_session)
    latest_portfolio_snapshot = portfolio_dao.retrieve_latest_snapshot()
    if latest_portfolio_snapshot is None:
        return all_trade_records

    ledger_anchor_timestamp = ensure_timezone_aware(latest_portfolio_snapshot.created_at)
    if ledger_anchor_timestamp is None:
        return all_trade_records

    trade_records_after_ledger_anchor: List[TradingTrade] = []
    for trade_record in all_trade_records:
        trade_timestamp = ensure_timezone_aware(trade_record.created_at)
        if trade_timestamp is None:
            continue
        if trade_timestamp > ledger_anchor_timestamp:
            trade_records_after_ledger_anchor.append(trade_record)
    return trade_records_after_ledger_anchor


def _compute_live_available_cash_usd() -> float:
    try:
        balances = fetch_stablecoin_balances_for_allowed_chains()
    except ConnectionError:
        cached_cash = trading_cache.get_available_cash_usd()
        if cached_cash is not None:
            logger.warning(
                "[TRADING][CASH] Live balances unavailable; using cached available cash %.2f USD",
                cached_cash,
            )
            return cached_cash
        raise
    return sum(balance.balance_raw for balance in balances)
