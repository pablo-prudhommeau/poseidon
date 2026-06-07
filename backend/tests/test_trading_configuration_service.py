from __future__ import annotations

import pytest

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_configuration_service import (
    TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE,
    TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE,
    WALLET_MNEMONIC_ENVIRONMENT_VARIABLE,
    validate_and_apply_trading_application_configuration,
    validate_live_wallet_configuration,
)
from src.core.trading.trading_chain_capability_service import (
    TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS,
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_structures import TradingConfigurationError
from src.core.trading.trading_dex_capability_service import (
    TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS,
    resolve_supported_trading_solana_dex_ids,
)


class _SettingsStub:
    TRADING_ALLOWED_CHAINS: list[str]
    TRADING_SOLANA_SUPPORTED_DEX_IDS: list[str]
    PAPER_MODE: bool = True
    WALLET_MNEMONIC: str = ""
    WALLET_DERIVATION_INDEX: int = 0
    TRADING_STABLECOIN_ADDRESS_SOLANA: str = ""
    TRADING_STABLECOIN_ADDRESS_BSC: str = ""
    TRADING_STABLECOIN_ADDRESS_BASE: str = ""
    TRADING_STABLECOIN_ADDRESS_AVALANCHE: str = ""

    def __init__(
            self,
            allowed_chains: list[str],
            supported_dex_ids: list[str],
    ) -> None:
        self.TRADING_ALLOWED_CHAINS = allowed_chains
        self.TRADING_SOLANA_SUPPORTED_DEX_IDS = supported_dex_ids


class _LiveWalletSettingsStub(_SettingsStub):
    PAPER_MODE = False
    WALLET_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    WALLET_DERIVATION_INDEX = 0
    TRADING_STABLECOIN_ADDRESS_SOLANA = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

    def __init__(self) -> None:
        super().__init__(
            allowed_chains=["solana"],
            supported_dex_ids=["pumpfun"],
        )


def test_validate_and_apply_trading_application_configuration_applies_defaults() -> None:
    validate_and_apply_trading_application_configuration(
        _SettingsStub(
            allowed_chains=["solana"],
            supported_dex_ids=["pumpfun", "pumpswap"],
        ),
    )

    assert resolve_trading_allowed_blockchain_networks() == [BlockchainNetwork.SOLANA]
    assert resolve_supported_trading_solana_dex_ids() == ["pumpfun", "pumpswap"]


def test_validate_and_apply_trading_application_configuration_accepts_supported_subset() -> None:
    validate_and_apply_trading_application_configuration(
        _SettingsStub(
            allowed_chains=["solana"],
            supported_dex_ids=["pumpfun"],
        ),
    )

    assert resolve_supported_trading_solana_dex_ids() == ["pumpfun"]

    validate_and_apply_trading_application_configuration(settings)


def test_validate_and_apply_trading_application_configuration_rejects_unsupported_blockchain() -> None:
    with pytest.raises(
            TradingConfigurationError,
            match=f"{TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE} contains unsupported blockchain 'bsc'",
    ):
        validate_and_apply_trading_application_configuration(
            _SettingsStub(
                allowed_chains=["bsc"],
                supported_dex_ids=["pumpfun"],
            ),
        )


def test_validate_and_apply_trading_application_configuration_rejects_unsupported_dex_id() -> None:
    with pytest.raises(
            TradingConfigurationError,
            match=f"{TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE} contains unsupported dex id 'raydium'",
    ):
        validate_and_apply_trading_application_configuration(
            _SettingsStub(
                allowed_chains=["solana"],
                supported_dex_ids=["raydium"],
            ),
        )


def test_validate_and_apply_trading_application_configuration_rejects_empty_blockchain_list() -> None:
    with pytest.raises(
            TradingConfigurationError,
            match=f"{TRADING_ALLOWED_CHAINS_ENVIRONMENT_VARIABLE} resolved to an empty list",
    ):
        validate_and_apply_trading_application_configuration(
            _SettingsStub(
                allowed_chains=[],
                supported_dex_ids=["pumpfun"],
            ),
        )


def test_validate_and_apply_trading_application_configuration_rejects_empty_dex_list() -> None:
    with pytest.raises(
            TradingConfigurationError,
            match=f"{TRADING_SOLANA_SUPPORTED_DEX_IDS_ENVIRONMENT_VARIABLE} resolved to an empty list",
    ):
        validate_and_apply_trading_application_configuration(
            _SettingsStub(
                allowed_chains=["solana"],
                supported_dex_ids=[],
            ),
        )


def test_application_supported_constants_define_application_ceiling() -> None:
    assert TRADING_APPLICATION_SUPPORTED_BLOCKCHAIN_NETWORKS == (BlockchainNetwork.SOLANA,)
    assert TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS == ("pumpfun", "pumpswap")


def test_validate_live_wallet_configuration_skips_paper_mode() -> None:
    validate_and_apply_trading_application_configuration(
        _SettingsStub(
            allowed_chains=["solana"],
            supported_dex_ids=["pumpfun"],
        ),
    )

    paper_settings = _LiveWalletSettingsStub()
    paper_settings.PAPER_MODE = True
    paper_settings.WALLET_MNEMONIC = ""

    validate_live_wallet_configuration(paper_settings)


def test_validate_live_wallet_configuration_rejects_missing_mnemonic_in_live_mode() -> None:
    validate_and_apply_trading_application_configuration(
        _SettingsStub(
            allowed_chains=["solana"],
            supported_dex_ids=["pumpfun"],
        ),
    )

    live_settings = _LiveWalletSettingsStub()
    live_settings.WALLET_MNEMONIC = ""

    with pytest.raises(
            TradingConfigurationError,
            match=f"{WALLET_MNEMONIC_ENVIRONMENT_VARIABLE} is required when PAPER_MODE=false",
    ):
        validate_live_wallet_configuration(live_settings)


def test_validate_live_wallet_configuration_rejects_missing_solana_stablecoin_in_live_mode() -> None:
    validate_and_apply_trading_application_configuration(
        _SettingsStub(
            allowed_chains=["solana"],
            supported_dex_ids=["pumpfun"],
        ),
    )

    live_settings = _LiveWalletSettingsStub()
    live_settings.TRADING_STABLECOIN_ADDRESS_SOLANA = ""

    with pytest.raises(
            TradingConfigurationError,
            match="TRADING_STABLECOIN_ADDRESS_SOLANA is required for enabled blockchain 'solana'",
    ):
        validate_live_wallet_configuration(live_settings)


def test_validate_live_wallet_configuration_accepts_valid_live_configuration() -> None:
    validate_and_apply_trading_application_configuration(
        _SettingsStub(
            allowed_chains=["solana"],
            supported_dex_ids=["pumpfun"],
        ),
    )

    validate_live_wallet_configuration(_LiveWalletSettingsStub())

    validate_and_apply_trading_application_configuration(settings)
