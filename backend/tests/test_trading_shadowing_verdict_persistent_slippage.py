from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.core.trading.shadowing.trading_shadowing_verdict_tracker import TradingShadowingVerdictTracker
from src.integrations.blockchain.blockchain_price_structures import (
    OnchainPricesByPairAddress,
    OnchainPricesFetchResult,
    PairAddressOnchainPrice,
)
from src.integrations.blockchain.solana.solana_structures import SolanaMintFreezeAuthoritySnapshot
from src.persistence.models import TradingShadowingProbe, TradingShadowingVerdict

_FIXED_NOW = datetime(2026, 8, 2, 22, 0, 0, tzinfo=timezone(timedelta(hours=2)))


def _build_probe() -> TradingShadowingProbe:
    return TradingShadowingProbe(
        id=1,
        token_symbol="SLIP",
        blockchain_network="solana",
        token_address="MintAddress1111111111111111111111111111",
        pair_address="PairAddress1111111111111111111111111111",
        dex_id="pumpswap",
        entry_price_usd=1.0,
        order_notional_value_usd=50.0,
        probed_at=_FIXED_NOW - timedelta(hours=8),
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
        transient_slippage_first_deferred_at=None,
    )


def _stub_dexscreener_price(probe: TradingShadowingProbe, price_usd: float) -> list[MagicMock]:
    return [
        MagicMock(
            chain_id=MagicMock(value="solana"),
            base_token=MagicMock(address=probe.token_address),
            pair_address=probe.pair_address,
            price_usd=price_usd,
        ),
    ]


def _stub_freeze_authority(probe: TradingShadowingProbe) -> list[SolanaMintFreezeAuthoritySnapshot]:
    return [
        SolanaMintFreezeAuthoritySnapshot(
            mint_address=probe.token_address,
            freeze_authority_address=None,
        ),
    ]


def _stub_onchain_price(probe: TradingShadowingProbe, price_usd: float) -> OnchainPricesFetchResult:
    return OnchainPricesFetchResult(
        onchain_prices=OnchainPricesByPairAddress(
            pair_address_prices=[
                PairAddressOnchainPrice(pair_address=probe.pair_address, price_usd=price_usd),
            ],
        ),
        had_infrastructure_failure=False,
    )


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.get_current_local_datetime", return_value=_FIXED_NOW)
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_first_transient_slippage_deferral_stamps_episode_start(
        resolve_snapshots_batch_mock: MagicMock,
        fetch_dexscreener_mock: MagicMock,
        fetch_onchain_prices_mock: MagicMock,
        _get_current_local_datetime_mock: MagicMock,
) -> None:
    probe = _build_probe()
    verdict = _build_verdict(probe)
    tracker = TradingShadowingVerdictTracker()

    # Dex below stop-loss; on-chain ~10% above dex => transient band (3%-30%)
    fetch_dexscreener_mock.return_value = _stub_dexscreener_price(probe, 0.70)
    resolve_snapshots_batch_mock.return_value = _stub_freeze_authority(probe)
    fetch_onchain_prices_mock.return_value = _stub_onchain_price(probe, 0.77)

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 0
    assert batch_statistics.deferred_transient_slippage_count == 1
    assert batch_statistics.resolved_staled_persistent_slippage_count == 0
    assert verdict.exit_reason is None
    assert verdict.transient_slippage_first_deferred_at == _FIXED_NOW


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.get_current_local_datetime", return_value=_FIXED_NOW)
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_ongoing_transient_slippage_episode_below_window_keeps_deferring(
        resolve_snapshots_batch_mock: MagicMock,
        fetch_dexscreener_mock: MagicMock,
        fetch_onchain_prices_mock: MagicMock,
        _get_current_local_datetime_mock: MagicMock,
) -> None:
    probe = _build_probe()
    verdict = _build_verdict(probe)
    episode_start = _FIXED_NOW - timedelta(hours=1)
    verdict.transient_slippage_first_deferred_at = episode_start
    tracker = TradingShadowingVerdictTracker()

    fetch_dexscreener_mock.return_value = _stub_dexscreener_price(probe, 0.70)
    resolve_snapshots_batch_mock.return_value = _stub_freeze_authority(probe)
    fetch_onchain_prices_mock.return_value = _stub_onchain_price(probe, 0.77)

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 0
    assert batch_statistics.deferred_transient_slippage_count == 1
    assert batch_statistics.resolved_staled_persistent_slippage_count == 0
    assert verdict.exit_reason is None
    assert verdict.transient_slippage_first_deferred_at == episode_start


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.get_current_local_datetime", return_value=_FIXED_NOW)
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_persistent_slippage_episode_beyond_window_stales_verdict(
        resolve_snapshots_batch_mock: MagicMock,
        fetch_dexscreener_mock: MagicMock,
        fetch_onchain_prices_mock: MagicMock,
        _get_current_local_datetime_mock: MagicMock,
) -> None:
    probe = _build_probe()
    verdict = _build_verdict(probe)
    verdict.transient_slippage_first_deferred_at = _FIXED_NOW - timedelta(hours=2, minutes=1)
    tracker = TradingShadowingVerdictTracker()

    fetch_dexscreener_mock.return_value = _stub_dexscreener_price(probe, 0.70)
    resolve_snapshots_batch_mock.return_value = _stub_freeze_authority(probe)
    fetch_onchain_prices_mock.return_value = _stub_onchain_price(probe, 0.77)

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 1
    assert batch_statistics.resolved_staled_persistent_slippage_count == 1
    assert batch_statistics.deferred_transient_slippage_count == 0
    assert verdict.exit_reason == "STALED"
    assert verdict.resolved_at == _FIXED_NOW
    assert verdict.realized_pnl_percentage == -100.0


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.get_current_local_datetime", return_value=_FIXED_NOW)
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_clean_onchain_deviation_resets_slippage_episode_and_resolves(
        resolve_snapshots_batch_mock: MagicMock,
        fetch_dexscreener_mock: MagicMock,
        fetch_onchain_prices_mock: MagicMock,
        _get_current_local_datetime_mock: MagicMock,
) -> None:
    probe = _build_probe()
    verdict = _build_verdict(probe)
    verdict.transient_slippage_first_deferred_at = _FIXED_NOW - timedelta(hours=1)
    tracker = TradingShadowingVerdictTracker()

    # Dex below stop-loss; on-chain within 3% of dex => clean resolution path
    fetch_dexscreener_mock.return_value = _stub_dexscreener_price(probe, 0.70)
    resolve_snapshots_batch_mock.return_value = _stub_freeze_authority(probe)
    fetch_onchain_prices_mock.return_value = _stub_onchain_price(probe, 0.714)

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 1
    assert batch_statistics.resolved_stop_loss_count == 1
    assert batch_statistics.deferred_transient_slippage_count == 0
    assert verdict.exit_reason == "STOP_LOSS"
    assert verdict.transient_slippage_first_deferred_at is None


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.get_current_local_datetime", return_value=_FIXED_NOW)
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_price_between_thresholds_resets_slippage_episode(
        resolve_snapshots_batch_mock: MagicMock,
        fetch_dexscreener_mock: MagicMock,
        fetch_onchain_prices_mock: MagicMock,
        _get_current_local_datetime_mock: MagicMock,
) -> None:
    probe = _build_probe()
    verdict = _build_verdict(probe)
    verdict.transient_slippage_first_deferred_at = _FIXED_NOW - timedelta(hours=1)
    tracker = TradingShadowingVerdictTracker()

    fetch_dexscreener_mock.return_value = _stub_dexscreener_price(probe, 1.0)
    resolve_snapshots_batch_mock.return_value = _stub_freeze_authority(probe)

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 0
    assert batch_statistics.deferred_transient_slippage_count == 0
    assert verdict.exit_reason is None
    assert verdict.transient_slippage_first_deferred_at is None
    fetch_onchain_prices_mock.assert_not_called()


@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.get_current_local_datetime", return_value=_FIXED_NOW)
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_onchain_prices_for_tokens_with_metadata")
@patch("src.core.trading.shadowing.trading_shadowing_verdict_tracker.fetch_dexscreener_token_information_list_sync")
@patch(
    "src.core.trading.shadowing.trading_shadowing_verdict_tracker.resolve_solana_mint_freeze_authority_snapshots_batch",
)
def test_aberrant_price_deviation_still_stales_immediately(
        resolve_snapshots_batch_mock: MagicMock,
        fetch_dexscreener_mock: MagicMock,
        fetch_onchain_prices_mock: MagicMock,
        _get_current_local_datetime_mock: MagicMock,
) -> None:
    probe = _build_probe()
    verdict = _build_verdict(probe)
    tracker = TradingShadowingVerdictTracker()

    # Dex below stop-loss; on-chain ~40% above dex => aberrant (>30%)
    fetch_dexscreener_mock.return_value = _stub_dexscreener_price(probe, 0.70)
    resolve_snapshots_batch_mock.return_value = _stub_freeze_authority(probe)
    fetch_onchain_prices_mock.return_value = _stub_onchain_price(probe, 0.98)

    batch_statistics = tracker._process_pending_verdict_batch([verdict])

    assert batch_statistics.resolved_verdict_count == 1
    assert batch_statistics.resolved_staled_aberrant_onchain_dex_price_count == 1
    assert batch_statistics.resolved_staled_persistent_slippage_count == 0
    assert verdict.exit_reason == "STALED"
