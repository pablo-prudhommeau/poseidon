from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.core.trading.shadowing.trading_shadowing_verdict_tracker import TradingShadowingVerdictTracker
from src.integrations.blockchain.solana.solana_structures import SolanaMintFreezeAuthoritySnapshot
from src.persistence.models import TradingShadowingProbe, TradingShadowingVerdict


def _build_probe() -> TradingShadowingProbe:
    return TradingShadowingProbe(
        id=1,
        token_symbol="HONEY",
        blockchain_network="solana",
        token_address="MintAddress1111111111111111111111111111",
        pair_address="PairAddress1111111111111111111111111111",
        dex_id="pumpswap",
        entry_price_usd=1.0,
        order_notional_value_usd=50.0,
        probed_at=datetime(2026, 6, 4, 12, 0, 0),
    )


def _build_verdict(probe: TradingShadowingProbe) -> TradingShadowingVerdict:
    return TradingShadowingVerdict(
        id=10,
        probe_id=probe.id,
        probe=probe,
        take_profit_tier_1_price=1.1,
        take_profit_tier_2_price=1.2,
        stop_loss_price=0.8,
        exit_reason=None,
    )


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_shadowing_verdict_marks_honeypot_when_freeze_authority_active(
        resolve_snapshots_batch_mock: MagicMock,
        fetch_dexscreener_mock: MagicMock,
        fetch_onchain_prices_mock: MagicMock,
) -> None:
    probe = _build_probe()
    verdict = _build_verdict(probe)
    tracker = TradingShadowingVerdictTracker()

    fetch_dexscreener_mock.return_value = [
        MagicMock(
            chain_id=MagicMock(value="solana"),
            base_token=MagicMock(address=probe.token_address),
            pair_address=probe.pair_address,
            price_usd=1.5,
        ),
    ]
    resolve_snapshots_batch_mock.return_value = [
        SolanaMintFreezeAuthoritySnapshot(
            mint_address=probe.token_address,
            freeze_authority_address="CreatorWallet1111111111111111111111111111",
        ),
    ]
    fetch_onchain_prices_mock.return_value = MagicMock(
        resolve_price_usd_for_pair_address=MagicMock(return_value=1.5),
    )

    resolved_count = tracker._process_pending_verdict_batch([verdict])

    assert resolved_count == 1
    assert verdict.exit_reason == "HONEYPOT"
    assert verdict.realized_pnl_percentage == -100.0
    assert verdict.realized_pnl_usd == -50.0
    assert verdict.is_profitable is False
    fetch_onchain_prices_mock.assert_not_called()
