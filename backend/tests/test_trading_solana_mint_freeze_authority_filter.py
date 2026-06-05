from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.trading.evaluators.trading_solana_mint_freeze_authority_filter import (
    SOLANA_MINT_FREEZE_AUTHORITY_ACTIVE_DECISION_REASON,
    evaluate_solana_mint_freeze_authority_for_buy,
)


@patch(
    "src.core.trading.evaluators.trading_solana_mint_freeze_authority_filter.is_solana_mint_blocked_by_active_freeze_authority",
)
def test_evaluate_solana_mint_freeze_authority_for_buy_rejects_blocked_mint(
        is_blocked_mock: MagicMock,
) -> None:
    is_blocked_mock.return_value = True

    decision = evaluate_solana_mint_freeze_authority_for_buy(
        token_mint_address="MintAddress1111111111111111111111111111",
    )

    assert decision.is_valid_for_entry is False
    assert decision.decision_reason == SOLANA_MINT_FREEZE_AUTHORITY_ACTIVE_DECISION_REASON


@patch(
    "src.core.trading.evaluators.trading_solana_mint_freeze_authority_filter.is_solana_mint_blocked_by_active_freeze_authority",
)
def test_evaluate_solana_mint_freeze_authority_for_buy_allows_clean_mint(
        is_blocked_mock: MagicMock,
) -> None:
    is_blocked_mock.return_value = False

    decision = evaluate_solana_mint_freeze_authority_for_buy(
        token_mint_address="MintAddress1111111111111111111111111111",
    )

    assert decision.is_valid_for_entry is True
    assert decision.decision_reason == "ok"
