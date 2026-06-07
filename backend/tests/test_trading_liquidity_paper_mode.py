from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.cache.trading_cache_payload_builders import build_trading_liquidity_payload


@patch("src.core.trading.cache.trading_cache_payload_builders.compute_available_cash_usd", return_value=6803.93)
@patch("src.core.trading.cache.trading_cache_payload_builders.settings")
def test_build_trading_liquidity_payload_paper_mode_does_not_require_wallet_mnemonic(
        settings_mock: MagicMock,
        compute_available_cash_usd_mock: MagicMock,
) -> None:
    settings_mock.PAPER_MODE = True
    settings_mock.WALLET_MNEMONIC = ""
    settings_mock.PAPER_MODE_VIRTUAL_WALLET_ADDRESS = "PaperMode1111111111111111111111111111111111"

    payload = build_trading_liquidity_payload()

    assert payload.mode == "PAPER"
    assert len(payload.blockchain_balances) == 1
    assert payload.blockchain_balances[0].blockchain_network == BlockchainNetwork.PAPER
    assert payload.blockchain_balances[0].wallet_address == settings_mock.PAPER_MODE_VIRTUAL_WALLET_ADDRESS
    assert compute_available_cash_usd_mock.call_count >= 1
