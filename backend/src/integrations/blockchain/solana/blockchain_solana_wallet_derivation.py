from __future__ import annotations

from eth_account.hdaccount.mnemonic import Language, Mnemonic
from solders.keypair import Keypair

_SOLANA_BIP44_PATH_TEMPLATE = "m/44'/501'/{wallet_derivation_index}'/0'"


def derive_solana_keypair_from_mnemonic(mnemonic: str, wallet_derivation_index: int) -> Keypair:
    normalized_mnemonic = mnemonic.strip()
    if not normalized_mnemonic:
        raise ValueError("Solana wallet derivation requires a non-empty mnemonic")

    if not Mnemonic(Language.ENGLISH).is_mnemonic_valid(normalized_mnemonic):
        raise ValueError("Solana wallet derivation requires a valid BIP39 mnemonic")

    seed = Mnemonic.to_seed(normalized_mnemonic, "")
    derivation_path = _SOLANA_BIP44_PATH_TEMPLATE.format(wallet_derivation_index=wallet_derivation_index)
    return Keypair.from_seed_and_derivation_path(seed, derivation_path)


def derive_solana_wallet_address_from_mnemonic(mnemonic: str, wallet_derivation_index: int) -> str:
    return str(derive_solana_keypair_from_mnemonic(mnemonic, wallet_derivation_index).pubkey())
