from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.core.trading.shadowing.trading_shadowing_verdict_tracker import TradingShadowingVerdictTracker
from src.integrations.blockchain.blockchain_price_structures import OnchainPricesByPairAddress, OnchainPricesFetchResult
from src.integrations.blockchain.solana.solana_structures import SolanaMintFreezeAuthoritySnapshot
from src.persistence.models import TradingShadowingProbe, TradingShadowingVerdict


def _build_probe(*, dex_id: str = "pumpswap") -> TradingShadowingProbe:
    return TradingShadowingProbe(
        id=1,
        token_symbol="DEAD",
        blockchain_network="solana",
        token_address="MintAddress1111111111111111111111111111",
        pair_address="PairAddress1111111111111111111111111111",
        dex_id=dex_id,
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


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_shadowing_verdict_stales_unrecoverable_onchain_price_instead_of_deferring(
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
            freeze_authority_address=None,
        ),
    ]
    fetch_onchain_prices_mock.return_value = OnchainPricesFetchResult(
        onchain_prices=OnchainPricesByPairAddress.empty(),
        had_infrastructure_failure=False,
    )

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 1
    assert batch_statistics.resolved_staled_unrecoverable_onchain_price_count == 1
    assert batch_statistics.deferred_onchain_price_unavailable_count == 0
    assert verdict.exit_reason == "STALED"


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_shadowing_verdict_defers_only_when_onchain_fetch_has_infrastructure_failure(
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
            freeze_authority_address=None,
        ),
    ]
    fetch_onchain_prices_mock.return_value = OnchainPricesFetchResult(
        onchain_prices=OnchainPricesByPairAddress.empty(),
        had_infrastructure_failure=True,
    )

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 0
    assert batch_statistics.deferred_onchain_price_unavailable_count == 1
    assert verdict.exit_reason is None
