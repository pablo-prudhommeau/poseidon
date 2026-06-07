from __future__ import annotations

from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.trading.gasreserve.trading_gas_reserve_service import (
    compute_net_deployable_cash_usd,
    compute_total_gas_refill_locked_stablecoin_usd,
    compute_total_wallet_auxiliary_assets_usd,
)
from src.core.trading.portfolio.trading_portfolio_structures import TradingPortfolioValuation
from src.core.trading.trading_service import (
    compute_holdings_and_unrealized_totals,
    compute_paper_deployable_cash_usd,
)
from src.core.utils.math_utils import decimal_from_primitive, quantize_2dp
from src.integrations.blockchain.blockchain_free_cash_service import fetch_stablecoin_balances_for_allowed_chains
from src.integrations.blockchain.blockchain_price_structures import OnchainPricesByPairAddress
from src.logging.logger import get_application_logger
from src.persistence.models import TradingPosition

logger = get_application_logger(__name__)


def build_trading_portfolio_valuation(
        database_session: Session,
        open_positions: list[TradingPosition],
        onchain_prices_by_pair_address: OnchainPricesByPairAddress,
) -> TradingPortfolioValuation:
    holdings_mark_to_market_usd, _ = compute_holdings_and_unrealized_totals(
        open_positions,
        onchain_prices_by_pair_address,
    )
    if settings.PAPER_MODE:
        deployable_cash_usd = compute_paper_deployable_cash_usd(database_session)
        wallet_auxiliary_assets_usd = 0.0
        total_gas_refill_locked_stablecoin_usd = 0.0
    else:
        blockchain_balances = fetch_stablecoin_balances_for_allowed_chains()
        total_stablecoin_usd = sum(balance.balance_raw for balance in blockchain_balances)
        total_gas_refill_locked_stablecoin_usd = compute_total_gas_refill_locked_stablecoin_usd()
        deployable_cash_usd = compute_net_deployable_cash_usd(total_stablecoin_usd)
        wallet_auxiliary_assets_usd = compute_total_wallet_auxiliary_assets_usd()
        logger.debug(
            "[TRADING][PORTFOLIO][VALUATION][LIVE] stablecoin=%.2f locked=%.2f deployable=%.2f holdings=%.2f wallet_auxiliary=%.2f",
            total_stablecoin_usd,
            total_gas_refill_locked_stablecoin_usd,
            deployable_cash_usd,
            holdings_mark_to_market_usd,
            wallet_auxiliary_assets_usd,
        )

    deployable_cash_usd = float(quantize_2dp(decimal_from_primitive(deployable_cash_usd)))
    holdings_mark_to_market_usd = float(quantize_2dp(decimal_from_primitive(holdings_mark_to_market_usd)))
    wallet_auxiliary_assets_usd = float(quantize_2dp(decimal_from_primitive(wallet_auxiliary_assets_usd)))
    total_gas_refill_locked_stablecoin_usd = float(
        quantize_2dp(decimal_from_primitive(total_gas_refill_locked_stablecoin_usd)),
    )
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
        "wallet_auxiliary=%.2f locked=%.2f sizing_capital=%.2f paper_mode=%s",
        total_equity_value,
        deployable_cash_usd,
        holdings_mark_to_market_usd,
        wallet_auxiliary_assets_usd,
        total_gas_refill_locked_stablecoin_usd,
        sizing_capital_usd,
        settings.PAPER_MODE,
    )
    return TradingPortfolioValuation(
        deployable_cash_usd=deployable_cash_usd,
        holdings_mark_to_market_usd=holdings_mark_to_market_usd,
        wallet_auxiliary_assets_usd=wallet_auxiliary_assets_usd,
        total_gas_refill_locked_stablecoin_usd=total_gas_refill_locked_stablecoin_usd,
        sizing_capital_usd=sizing_capital_usd,
        total_equity_value=total_equity_value,
    )
