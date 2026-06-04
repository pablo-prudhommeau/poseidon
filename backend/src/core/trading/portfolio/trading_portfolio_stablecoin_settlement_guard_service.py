from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_pending_stablecoin_settlement: Optional["PendingStablecoinSettlement"] = None


class PendingStablecoinSettlement(BaseModel):
    baseline_deployable_cash_usd: float
    confirmed_swap_transaction_signature: str


class PendingStablecoinSettlementIncompleteError(Exception):
    """Deployable stablecoin has not yet reflected a confirmed sell swap."""


def register_live_sell_stablecoin_settlement_pending(
        confirmed_swap_transaction_signature: str,
        baseline_deployable_cash_usd: float,
) -> None:
    global _pending_stablecoin_settlement

    if not confirmed_swap_transaction_signature:
        return

    _pending_stablecoin_settlement = PendingStablecoinSettlement(
        baseline_deployable_cash_usd=baseline_deployable_cash_usd,
        confirmed_swap_transaction_signature=confirmed_swap_transaction_signature,
    )
    logger.debug(
        "[TRADING][PORTFOLIO][SETTLEMENT] Registered confirmed sell awaiting deployable refresh — "
        "baseline_deployable=%.2f transaction_signature=%s",
        baseline_deployable_cash_usd,
        confirmed_swap_transaction_signature,
    )


def clear_pending_stablecoin_settlement() -> None:
    global _pending_stablecoin_settlement
    _pending_stablecoin_settlement = None


def should_skip_live_portfolio_for_pending_stablecoin_settlement(
        current_deployable_cash_usd: float,
) -> bool:
    global _pending_stablecoin_settlement

    pending_settlement = _pending_stablecoin_settlement
    if pending_settlement is None:
        return False

    if current_deployable_cash_usd > pending_settlement.baseline_deployable_cash_usd:
        logger.debug(
            "[TRADING][PORTFOLIO][SETTLEMENT] Deployable stablecoin reflects confirmed sell — "
            "baseline_deployable=%.2f current_deployable=%.2f transaction_signature=%s",
            pending_settlement.baseline_deployable_cash_usd,
            current_deployable_cash_usd,
            pending_settlement.confirmed_swap_transaction_signature,
        )
        _pending_stablecoin_settlement = None
        return False

    logger.debug(
        "[TRADING][PORTFOLIO][SETTLEMENT] Skipping live portfolio/liquidity rebuild — "
        "confirmed sell not yet reflected in deployable stablecoin "
        "(baseline_deployable=%.2f current_deployable=%.2f transaction_signature=%s)",
        pending_settlement.baseline_deployable_cash_usd,
        current_deployable_cash_usd,
        pending_settlement.confirmed_swap_transaction_signature,
    )
    return True
