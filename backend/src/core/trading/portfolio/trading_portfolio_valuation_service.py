from __future__ import annotations

from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.trading.portfolio.trading_portfolio_solana_wallet_auxiliary_service import (
    resolve_solana_locked_token_account_capital_usd,
    resolve_solana_token_account_rent_breakdown,
)
from src.core.trading.portfolio.trading_portfolio_structures import TradingPortfolioValuation
from src.core.trading.trading_service import (
    compute_holdings_and_unrealized_totals,
    compute_paper_deployable_cash_usd,
)
from src.core.utils.math_utils import decimal_from_primitive, quantize_2dp
from src.integrations.blockchain.blockchain_free_cash_service import fetch_stablecoin_balances_for_allowed_chains
from src.logging.logger import get_application_logger
from src.persistence.models import TradingPosition

logger = get_application_logger(__name__)


def build_trading_portfolio_valuation(
        database_session: Session,
        open_positions: list[TradingPosition],
        prices_by_pair_address: dict[str, float],
) -> TradingPortfolioValuation:
    holdings_mark_to_market_usd, _ = compute_holdings_and_unrealized_totals(open_positions, prices_by_pair_address)
    if settings.PAPER_MODE:
        deployable_cash_usd = compute_paper_deployable_cash_usd(database_session)
        wallet_auxiliary_assets_usd = 0.0
    else:
        blockchain_balances = fetch_stablecoin_balances_for_allowed_chains()
        deployable_cash_usd = sum(balance.balance_raw for balance in blockchain_balances)
        native_gas_balance_usd = sum(balance.native_token_balance_usd for balance in blockchain_balances)
        rent_breakdown = resolve_solana_token_account_rent_breakdown()
        locked_token_account_capital_usd = resolve_solana_locked_token_account_capital_usd(rent_breakdown)
        wallet_auxiliary_assets_usd = float(
            quantize_2dp(
                decimal_from_primitive(native_gas_balance_usd)
                + decimal_from_primitive(locked_token_account_capital_usd),
            ),
        )
        logger.debug(
            "[TRADING][PORTFOLIO][VALUATION][LIVE] deployable=%.2f holdings=%.2f native_gas=%.2f "
            "locked_account_capital=%.2f wallet_auxiliary=%.2f",
            deployable_cash_usd,
            holdings_mark_to_market_usd,
            native_gas_balance_usd,
            locked_token_account_capital_usd,
            wallet_auxiliary_assets_usd,
        )

    deployable_cash_usd = float(quantize_2dp(decimal_from_primitive(deployable_cash_usd)))
    holdings_mark_to_market_usd = float(quantize_2dp(decimal_from_primitive(holdings_mark_to_market_usd)))
    wallet_auxiliary_assets_usd = float(quantize_2dp(decimal_from_primitive(wallet_auxiliary_assets_usd)))
    sizing_capital_usd = float(
        quantize_2dp(
            decimal_from_primitive(deployable_cash_usd) + decimal_from_primitive(holdings_mark_to_market_usd),
        ),
    )
    total_equity_value = float(
        quantize_2dp(
            decimal_from_primitive(deployable_cash_usd)
            + decimal_from_primitive(holdings_mark_to_market_usd)
            + decimal_from_primitive(wallet_auxiliary_assets_usd),
        ),
    )
    logger.info(
        "[TRADING][PORTFOLIO][VALUATION] Snapshot inputs — equity=%.2f deployable=%.2f holdings=%.2f "
        "wallet_auxiliary=%.2f sizing_capital=%.2f paper_mode=%s",
        total_equity_value,
        deployable_cash_usd,
        holdings_mark_to_market_usd,
        wallet_auxiliary_assets_usd,
        sizing_capital_usd,
        settings.PAPER_MODE,
    )
    return TradingPortfolioValuation(
        deployable_cash_usd=deployable_cash_usd,
        holdings_mark_to_market_usd=holdings_mark_to_market_usd,
        wallet_auxiliary_assets_usd=wallet_auxiliary_assets_usd,
        sizing_capital_usd=sizing_capital_usd,
        total_equity_value=total_equity_value,
    )
