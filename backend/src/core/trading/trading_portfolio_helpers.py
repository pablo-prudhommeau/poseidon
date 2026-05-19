from __future__ import annotations

from typing import Iterable

from src.api.http.api_schemas import TradingTradePayload
from src.core.trading.trading_service import (
    compute_holdings_and_unrealized_totals,
    compute_realized_profit_and_loss_totals,
)
from src.core.trading.trading_structures import TradingPortfolio, TradingPortfolioEquityCurvePoint
from src.persistence.models import TradingPortfolioSnapshot, TradingPosition


def build_trading_portfolio(
        portfolio_snapshot: TradingPortfolioSnapshot,
        trades: list[TradingTradePayload],
        open_positions: Iterable[TradingPosition],
        prices_by_pair_address: dict[str, float],
        equity_curve: list[TradingPortfolioEquityCurvePoint],
) -> TradingPortfolio:
    _, unrealized_profit_and_loss = compute_holdings_and_unrealized_totals(
        open_positions,
        prices_by_pair_address,
    )
    realized_profit_and_loss_total, realized_profit_and_loss_24h = compute_realized_profit_and_loss_totals(
        trades,
        cutoff_hours=24,
    )

    return TradingPortfolio(
        total_equity_value=portfolio_snapshot.total_equity_value,
        available_cash_balance=portfolio_snapshot.available_cash_balance,
        active_holdings_value=portfolio_snapshot.active_holdings_value,
        created_at=portfolio_snapshot.created_at,
        equity_curve=equity_curve,
        unrealized_profit_and_loss=unrealized_profit_and_loss,
        realized_profit_and_loss_24h=realized_profit_and_loss_24h,
        realized_profit_and_loss_total=realized_profit_and_loss_total,
    )
