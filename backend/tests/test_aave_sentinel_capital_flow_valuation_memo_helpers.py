from __future__ import annotations

from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_valuation_memo_helpers import (
    build_historical_asset_price_lookup_key,
    create_empty_capital_flow_valuation_memo,
    remember_valuation_memo_historical_asset_price_usd,
    resolve_valuation_memo_historical_asset_price_usd,
)


def test_valuation_memo_historical_asset_price_is_stored_by_lookup_key() -> None:
    valuation_memo = create_empty_capital_flow_valuation_memo()
    lookup_key = build_historical_asset_price_lookup_key(
        block_number=42,
        contract_address="0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
    )
    remember_valuation_memo_historical_asset_price_usd(
        valuation_memo=valuation_memo,
        lookup_key=lookup_key,
        asset_price_usd=12.5,
    )
    resolved_price = resolve_valuation_memo_historical_asset_price_usd(
        valuation_memo=valuation_memo,
        lookup_key=lookup_key,
    )
    assert resolved_price == 12.5
    assert len(valuation_memo.historical_asset_prices) == 1
