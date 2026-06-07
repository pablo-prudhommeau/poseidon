from __future__ import annotations

from bip_utils import Bip39SeedGenerator, Bip32Slip10Ed25519
from solders.keypair import Keypair


def derive_solana_keypair_from_mnemonic(mnemonic: str, wallet_derivation_index: int) -> Keypair:
    normalized_mnemonic = mnemonic.strip()
    if not normalized_mnemonic:
        raise ValueError("Solana wallet derivation requires a non-empty mnemonic")

    seed = Bip39SeedGenerator(normalized_mnemonic).Generate("")
    bip32_node = Bip32Slip10Ed25519.FromSeed(seed)
    derivation_path = f"m/44'/501'/{wallet_derivation_index}'/0'"
    derived_node = bip32_node.DerivePath(derivation_path)
    raw_private_key = derived_node.PrivateKey().Raw().ToBytes()
    return Keypair.from_seed(raw_private_key)


def derive_solana_wallet_address_from_mnemonic(mnemonic: str, wallet_derivation_index: int) -> str:
    return str(derive_solana_keypair_from_mnemonic(mnemonic, wallet_derivation_index).pubkey())
