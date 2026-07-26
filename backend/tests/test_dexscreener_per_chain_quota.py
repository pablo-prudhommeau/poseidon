from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.integrations.dexscreener.dexscreener_helpers import apply_per_chain_trending_quota
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerLiquidityStatistics,
    DexscreenerToken,
    DexscreenerTokenInformation,
    DexscreenerVolumeStatistics,
)


def _build_token_information(
        *,
        chain: BlockchainNetwork,
        pair_address: str,
        volume_h24: float,
) -> DexscreenerTokenInformation:
    return DexscreenerTokenInformation(
        chain_id=chain,
        dex_id="test-dex",
        pair_address=pair_address,
        base_token=DexscreenerToken(address=f"token-{pair_address}", name="Test", symbol="TEST"),
        quote_token=DexscreenerToken(address=f"quote-{pair_address}", name="Quote", symbol="USD"),
        price_usd=1.0,
        liquidity=DexscreenerLiquidityStatistics(usd=10000.0),
        volume=DexscreenerVolumeStatistics(h24=volume_h24),
    )


def test_apply_per_chain_trending_quota_balances_allowed_chains() -> None:
    ranked = [
        _build_token_information(chain=BlockchainNetwork.SOLANA, pair_address="sol-1", volume_h24=1000.0),
        _build_token_information(chain=BlockchainNetwork.SOLANA, pair_address="sol-2", volume_h24=900.0),
        _build_token_information(chain=BlockchainNetwork.SOLANA, pair_address="sol-3", volume_h24=800.0),
        _build_token_information(chain=BlockchainNetwork.BASE, pair_address="base-1", volume_h24=700.0),
        _build_token_information(chain=BlockchainNetwork.BSC, pair_address="bsc-1", volume_h24=600.0),
        _build_token_information(chain=BlockchainNetwork.ROBINHOOD, pair_address="rh-1", volume_h24=500.0),
    ]

    selected = apply_per_chain_trending_quota(
        ranked_token_information=ranked,
        page_size=4,
        allowed_blockchain_networks=[
            BlockchainNetwork.SOLANA,
            BlockchainNetwork.ROBINHOOD,
            BlockchainNetwork.BASE,
            BlockchainNetwork.BSC,
        ],
    )

    selected_chains = {item.chain_id for item in selected}
    assert len(selected) == 4
    assert BlockchainNetwork.SOLANA in selected_chains
    assert BlockchainNetwork.BASE in selected_chains
    assert BlockchainNetwork.BSC in selected_chains
    assert BlockchainNetwork.ROBINHOOD in selected_chains
