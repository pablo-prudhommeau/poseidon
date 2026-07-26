from __future__ import annotations

from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    convert_sqrt_price_x64_to_token0_price_in_token1,
    resolve_sqrt_price_x64_pool_price,
    resolve_two_sided_pool_price_from_reserves,
)
from src.integrations.blockchain.solana.solana_structures import SOLANA_WRAPPED_SOL_MINT


def test_resolve_two_sided_pool_price_from_reserves_for_base_token() -> None:
    parsed_price = resolve_two_sided_pool_price_from_reserves(
        target_token_address="base-mint",
        token_mint_a="base-mint",
        token_mint_b="quote-mint",
        reserve_a_raw=1_000_000,
        reserve_b_raw=2_000_000,
        decimals_a=6,
        decimals_b=6,
    )

    assert parsed_price is not None
    assert parsed_price.quote_token_mint == "quote-mint"
    assert abs(parsed_price.price_in_quote_token - 2.0) < 1e-12


def test_resolve_two_sided_pool_price_from_reserves_for_quote_token() -> None:
    parsed_price = resolve_two_sided_pool_price_from_reserves(
        target_token_address="quote-mint",
        token_mint_a="base-mint",
        token_mint_b="quote-mint",
        reserve_a_raw=1_000_000,
        reserve_b_raw=2_000_000,
        decimals_a=6,
        decimals_b=6,
    )

    assert parsed_price is not None
    assert parsed_price.quote_token_mint == "base-mint"
    assert abs(parsed_price.price_in_quote_token - 0.5) < 1e-12


def test_convert_sqrt_price_x64_to_token0_price_in_token1_for_equal_decimals() -> None:
    sqrt_price_x64 = int((2**64) * (2.0 ** 0.5))
    price = convert_sqrt_price_x64_to_token0_price_in_token1(
        sqrt_price_x64=sqrt_price_x64,
        decimals_token0=9,
        decimals_token1=9,
    )

    assert price is not None
    assert abs(price - 2.0) < 1e-6


def test_resolve_sqrt_price_x64_pool_price_targets_token0() -> None:
    sqrt_price_x64 = int((2**64) * (3.0 ** 0.5))
    parsed_price = resolve_sqrt_price_x64_pool_price(
        target_token_address=SOLANA_WRAPPED_SOL_MINT,
        token_mint_0=SOLANA_WRAPPED_SOL_MINT,
        token_mint_1="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        sqrt_price_x64=sqrt_price_x64,
        decimals_token0=9,
        decimals_token1=6,
    )

    assert parsed_price is not None
    assert parsed_price.quote_token_mint == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert parsed_price.price_in_quote_token > 0.0
