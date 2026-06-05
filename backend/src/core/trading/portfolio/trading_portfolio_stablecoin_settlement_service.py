from __future__ import annotations

import time

from src.core.trading.portfolio.trading_portfolio_structures import (
    StablecoinSwapSettlementDirection,
    StablecoinSwapSettlementPollResult,
)
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.blockchain_free_cash_service import fetch_stablecoin_balances_for_allowed_chains
from src.integrations.blockchain.solana.solana_onchain_wallet_context_service import (
    invalidate_solana_onchain_wallet_context_cache,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

STABLECOIN_DEPLOYABLE_POLL_INTERVAL_SECONDS = 2.0
STABLECOIN_DEPLOYABLE_POLL_TIMEOUT_SECONDS = 30.0


def resolve_total_deployable_stablecoin_cash_usd(force_refresh: bool = False) -> float:
    blockchain_balances = fetch_stablecoin_balances_for_allowed_chains(force_refresh=force_refresh)
    return sum(blockchain_balance.balance_raw for blockchain_balance in blockchain_balances)


def poll_deployable_stablecoin_until_swap_settled(
        deployable_cash_before_swap_usd: float,
        settlement_direction: StablecoinSwapSettlementDirection,
        transaction_signature: str,
) -> StablecoinSwapSettlementPollResult:
    invalidate_solana_onchain_wallet_context_cache()
    deadline_timestamp = time.monotonic() + STABLECOIN_DEPLOYABLE_POLL_TIMEOUT_SECONDS
    poll_attempt_count = 0
    last_observed_deployable_cash_usd = deployable_cash_before_swap_usd

    while time.monotonic() < deadline_timestamp:
        poll_attempt_count += 1
        try:
            current_deployable_cash_usd = resolve_total_deployable_stablecoin_cash_usd(force_refresh=True)
        except BlockchainRpcUnavailableError as rpc_unavailable_error:
            logger.debug(
                "[TRADING][PORTFOLIO][SETTLEMENT] Deployable polling RPC unavailable — "
                "transaction_signature=%s poll_attempt_count=%d failure_reason=%s",
                transaction_signature,
                poll_attempt_count,
                rpc_unavailable_error.failure_reason.value,
            )
            time.sleep(STABLECOIN_DEPLOYABLE_POLL_INTERVAL_SECONDS)
            continue

        last_observed_deployable_cash_usd = current_deployable_cash_usd
        swap_settled_on_chain = _is_swap_reflected_in_deployable_cash(
            deployable_cash_before_swap_usd=deployable_cash_before_swap_usd,
            current_deployable_cash_usd=current_deployable_cash_usd,
            settlement_direction=settlement_direction,
        )
        if swap_settled_on_chain:
            logger.debug(
                "[TRADING][PORTFOLIO][SETTLEMENT] Deployable stablecoin reflects confirmed swap — "
                "settlement_direction=%s transaction_signature=%s poll_attempt_count=%d "
                "deployable_before=%.2f deployable_after=%.2f",
                settlement_direction.value,
                transaction_signature,
                poll_attempt_count,
                deployable_cash_before_swap_usd,
                current_deployable_cash_usd,
            )
            return StablecoinSwapSettlementPollResult(
                swap_settled_on_chain=True,
                deployable_cash_usd=current_deployable_cash_usd,
                transaction_signature=transaction_signature,
            )

        time.sleep(STABLECOIN_DEPLOYABLE_POLL_INTERVAL_SECONDS)

    logger.warning(
        "[TRADING][PORTFOLIO][SETTLEMENT] Deployable polling completed without swap reflection — "
        "settlement_direction=%s transaction_signature=%s poll_attempt_count=%d "
        "deployable_before=%.2f last_observed_deployable=%.2f",
        settlement_direction.value,
        transaction_signature,
        poll_attempt_count,
        deployable_cash_before_swap_usd,
        last_observed_deployable_cash_usd,
    )
    return StablecoinSwapSettlementPollResult(
        swap_settled_on_chain=False,
        deployable_cash_usd=last_observed_deployable_cash_usd,
        transaction_signature=transaction_signature,
    )


def _is_swap_reflected_in_deployable_cash(
        deployable_cash_before_swap_usd: float,
        current_deployable_cash_usd: float,
        settlement_direction: StablecoinSwapSettlementDirection,
) -> bool:
    if settlement_direction == StablecoinSwapSettlementDirection.BUY_DEBIT:
        return current_deployable_cash_usd < deployable_cash_before_swap_usd
    return current_deployable_cash_usd > deployable_cash_before_swap_usd
