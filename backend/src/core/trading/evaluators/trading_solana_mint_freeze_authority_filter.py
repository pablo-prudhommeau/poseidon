from __future__ import annotations

from src.core.trading.trading_structures import TradingPreEntryDecision
from src.integrations.blockchain.solana.solana_mint_freeze_authority_service import (
    is_solana_mint_blocked_by_active_freeze_authority,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SOLANA_MINT_FREEZE_AUTHORITY_ACTIVE_DECISION_REASON = "solana_mint_freeze_authority_active"


def evaluate_solana_mint_freeze_authority_for_buy(token_mint_address: str) -> TradingPreEntryDecision:
    normalized_token_mint_address = token_mint_address.strip()
    if not normalized_token_mint_address:
        return TradingPreEntryDecision(
            is_valid_for_entry=False,
            decision_reason=SOLANA_MINT_FREEZE_AUTHORITY_ACTIVE_DECISION_REASON,
        )

    if is_solana_mint_blocked_by_active_freeze_authority(mint_address=normalized_token_mint_address):
        logger.info(
            "[TRADING][FILTER][SOLANA][FREEZE_AUTHORITY] Buy rejected — mint_address_prefix=%s",
            normalized_token_mint_address[:12],
        )
        return TradingPreEntryDecision(
            is_valid_for_entry=False,
            decision_reason=SOLANA_MINT_FREEZE_AUTHORITY_ACTIVE_DECISION_REASON,
        )

    logger.debug(
        "[TRADING][FILTER][SOLANA][FREEZE_AUTHORITY] Buy allowed — mint_address_prefix=%s",
        normalized_token_mint_address[:12],
    )
    return TradingPreEntryDecision(is_valid_for_entry=True, decision_reason="ok")
