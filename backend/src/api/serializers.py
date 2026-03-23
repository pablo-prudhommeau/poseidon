from __future__ import annotations

from src.api.http.api_schemas import (
    TradePayload,
    PositionPayload,
    PortfolioPayload,
    EquityCurvePointPayload,
    AnalyticsPayload,
    AnalyticsScoresPayload,
    AnalyticsAiPayload,
    AnalyticsFundamentalsPayload,
    AnalyticsDecisionPayload,
    AnalyticsOutcomePayload,
    DcaOrderPayload,
    DcaStrategyPayload,
)
from src.core.structures.structures import EquityCurve
from src.core.utils.date_utils import format_datetime_to_local_iso
from src.core.utils.symbol_utils import get_currency_symbol
from src.integrations.aave.aave_structures import AaveLiveMetrics
from src.logging.logger import get_logger
from src.persistence.models import Trade, Position, PortfolioSnapshot, Analytics, DcaOrder, DcaStrategy

logger = get_logger(__name__)


def serialize_trade(trade: Trade) -> TradePayload:
    return TradePayload(
        id=trade.id,
        side=trade.side.value,
        symbol=trade.symbol,
        chain=trade.chain,
        price=trade.price,
        qty=trade.qty,
        fee=trade.fee,
        pnl=trade.pnl,
        status=trade.status.value,
        tokenAddress=trade.tokenAddress,
        pairAddress=trade.pairAddress,
        tx_hash=trade.tx_hash,
        created_at=format_datetime_to_local_iso(trade.created_at),
    )


def serialize_position(position: Position, last_price: float) -> PositionPayload:
    return PositionPayload(
        id=position.id,
        symbol=position.symbol,
        tokenAddress=position.tokenAddress,
        pairAddress=position.pairAddress,
        qty=position.open_quantity,
        entry=position.entry,
        tp1=position.tp1,
        tp2=position.tp2,
        stop=position.stop,
        phase=position.phase.value,
        chain=position.chain,
        opened_at=format_datetime_to_local_iso(position.opened_at),
        updated_at=format_datetime_to_local_iso(position.updated_at),
        closed_at=format_datetime_to_local_iso(position.closed_at),
        last_price=last_price,
    )


def serialize_portfolio(
        snapshot: PortfolioSnapshot,
        equity_curve: EquityCurve,
        realized_total: float,
        realized_24h: float,
        unrealized: float,
) -> PortfolioPayload:
    return PortfolioPayload(
        equity=snapshot.equity,
        cash=snapshot.cash,
        holdings=snapshot.holdings,
        updated_at=format_datetime_to_local_iso(snapshot.created_at),
        equity_curve=[
            EquityCurvePointPayload(timestamp=p.timestamp, equity=p.equity)
            for p in equity_curve.points
        ],
        unrealized_pnl=unrealized,
        realized_pnl_total=realized_total,
        realized_pnl_24h=realized_24h,
    )


def serialize_analytics(row: Analytics) -> AnalyticsPayload:
    return AnalyticsPayload(
        id=row.id,
        symbol=row.symbol,
        chain=row.chain,
        tokenAddress=row.tokenAddress,
        pairAddress=row.pairAddress,
        evaluatedAt=format_datetime_to_local_iso(row.evaluated_at),
        rank=row.rank,
        scores=AnalyticsScoresPayload(
            quality=row.quality_score,
            statistics=row.statistics_score,
            entry=row.entry_score,
            final=row.final_score,
        ),
        ai=AnalyticsAiPayload(
            probabilityTp1BeforeSl=row.ai_probability_tp1_before_sl,
            qualityScoreDelta=row.ai_quality_score_delta,
        ),
        fundamentals=AnalyticsFundamentalsPayload(
            tokenAgeHours=row.token_age_hours,
            volume5mUsd=row.volume5m_usd,
            volume1hUsd=row.volume1h_usd,
            volume6hUsd=row.volume6h_usd,
            volume24hUsd=row.volume24h_usd,
            liquidityUsd=row.liquidity_usd,
            pct5m=row.pct_5m,
            pct1h=row.pct_1h,
            pct6h=row.pct_6h,
            pct24h=row.pct_24h,
            tx5m=row.tx_5m,
            tx1h=row.tx_1h,
            tx6h=row.tx_6h,
            tx24h=row.tx_24h,
        ),
        decision=AnalyticsDecisionPayload(
            action=row.decision,
            reason=row.decision_reason,
            sizingMultiplier=row.sizing_multiplier,
            orderNotionalUsd=row.order_notional_usd,
            freeCashBeforeUsd=row.free_cash_before_usd,
            freeCashAfterUsd=row.free_cash_after_usd,
        ),
        outcome=AnalyticsOutcomePayload(
            hasOutcome=row.has_outcome,
            tradeId=row.outcome_trade_id,
            closedAt=format_datetime_to_local_iso(row.outcome_closed_at),
            holdingMinutes=row.outcome_holding_minutes,
            pnlPct=row.outcome_pnl_pct,
            pnlUsd=row.outcome_pnl_usd,
            wasProfit=row.outcome_was_profit,
            exitReason=row.outcome_exit_reason,
        ),
        rawScreener=row.raw_dexscreener,
        rawSettings=row.raw_settings,
    )


def serialize_dca_order(order: DcaOrder) -> DcaOrderPayload:
    return DcaOrderPayload(
        id=order.id,
        strategy_id=order.strategy_id,
        planned_date=format_datetime_to_local_iso(order.planned_date),
        planned_amount=order.planned_amount,
        executed_amount_in=order.executed_amount_in,
        executed_amount_out=order.executed_amount_out,
        status=order.status.value,
        transaction_hash=order.transaction_hash,
        execution_price=order.execution_price,
        executed_at=format_datetime_to_local_iso(order.executed_at),
    )


def serialize_dca_strategy(strategy: DcaStrategy, live_metrics: AaveLiveMetrics) -> DcaStrategyPayload:
    return DcaStrategyPayload(
        id=strategy.id,
        chain=strategy.chain,
        asset_in_symbol=strategy.asset_in_symbol,
        asset_in_address=strategy.asset_in_address,
        asset_in_decimals=strategy.asset_in_decimals,
        asset_in_currency_symbol=get_currency_symbol(strategy.asset_in_symbol),
        asset_out_symbol=strategy.asset_out_symbol,
        asset_out_address=strategy.asset_out_address,
        asset_out_currency_symbol=get_currency_symbol(strategy.asset_out_symbol),
        binance_pair=strategy.binance_pair,
        total_budget=strategy.total_budget,
        total_executions=strategy.total_executions,
        amount_per_order=strategy.amount_per_order,
        slippage=strategy.slippage,
        pru_elasticity_factor=strategy.pru_elasticity_factor,
        cycle_index=strategy.cycle_index,
        previous_ath=strategy.previous_ath,
        previous_bull_amplitude_pct=strategy.previous_bull_amplitude_pct,
        flattening_factor=strategy.flattening_factor,
        bear_bottom_multiplier=strategy.bear_bottom_multiplier,
        minimum_bull_multiplier=strategy.minimum_bull_multiplier,
        aave_estimated_apy=strategy.aave_estimated_apy,
        realized_aave_yield=strategy.realized_aave_yield,
        last_yield_calculation_at=format_datetime_to_local_iso(strategy.last_yield_calculation_at),
        start_date=format_datetime_to_local_iso(strategy.start_date),
        end_date=format_datetime_to_local_iso(strategy.end_date),
        status=strategy.status.value,
        bypass_approval=strategy.bypass_approval,
        dry_powder=strategy.dry_powder,
        deployed_amount=strategy.deployed_amount,
        average_purchase_price=strategy.average_purchase_price,
        backtest_payload=strategy.backtest_payload,
        created_at=format_datetime_to_local_iso(strategy.created_at),
        updated_at=format_datetime_to_local_iso(strategy.updated_at),
        orders=[serialize_dca_order(o) for o in (strategy.orders or [])],
        live_aave_apy=live_metrics.supply_apy,
        live_market_price=live_metrics.asset_out_price_usd
    )
