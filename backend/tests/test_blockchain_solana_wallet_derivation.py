from __future__ import annotations

import pytest

from src.integrations.blockchain.solana.blockchain_solana_wallet_derivation import (
    derive_solana_keypair_from_mnemonic,
    derive_solana_wallet_address_from_mnemonic,
)

_TEST_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)


def test_derive_solana_wallet_address_matches_slip10_ed25519_vectors() -> None:
    assert derive_solana_wallet_address_from_mnemonic(_TEST_MNEMONIC, 0) == (
        "HAgk14JpMQLgt6rVgv7cBQFJWFto5Dqxi472uT3DKpqk"
    )
    assert derive_solana_wallet_address_from_mnemonic(_TEST_MNEMONIC, 1) == (
        "Hh8QwFUA6MtVu1qAoq12ucvFHNwCcVTV7hpWjeY1Hztb"
    )


def test_derive_solana_keypair_rejects_empty_mnemonic() -> None:
    with pytest.raises(ValueError, match="non-empty mnemonic"):
        derive_solana_keypair_from_mnemonic("   ", 0)


def test_derive_solana_keypair_rejects_invalid_mnemonic() -> None:
    with pytest.raises(ValueError, match="valid BIP39 mnemonic"):
        derive_solana_keypair_from_mnemonic("not a valid mnemonic phrase at all", 0)
