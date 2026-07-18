from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelReserveRegistry,
    AaveSentinelStrategy,
    AaveSentinelStrategyKind,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_long_liquidation_price_usd,
    compute_short_liquidation_price_usd,
    compute_strategy_leverage,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    resolve_stablecoin_symbols,
)


def resolve_active_strategies(
        detected_assets: list[AaveSentinelAssetSnapshot],
        reserve_registry: AaveSentinelReserveRegistry,
) -> list[AaveSentinelStrategy]:
    stablecoin_symbols = resolve_stablecoin_symbols(reserve_registry=reserve_registry)
    active_strategies: list[AaveSentinelStrategy] = []

    short_strategy = _resolve_short_strategy(
        detected_assets=detected_assets,
        stablecoin_symbols=stablecoin_symbols,
    )
    if short_strategy is not None:
        active_strategies.append(short_strategy)

    long_strategy = _resolve_long_strategy(
        detected_assets=detected_assets,
        stablecoin_symbols=stablecoin_symbols,
    )
    if long_strategy is not None:
        active_strategies.append(long_strategy)

    return active_strategies


def _resolve_short_strategy(
        detected_assets: list[AaveSentinelAssetSnapshot],
        stablecoin_symbols: frozenset[str],
) -> Optional[AaveSentinelStrategy]:
    volatile_debt_assets = [
        asset
        for asset in detected_assets
        if asset.symbol not in stablecoin_symbols and asset.debt_amount > TOKEN_AMOUNT_DUST_EPSILON
    ]
    if not volatile_debt_assets:
        return None

    main_debt_asset = max(volatile_debt_assets, key=lambda asset_snapshot: asset_snapshot.debt_value_usd)
    stable_collateral_assets = [
        asset
        for asset in detected_assets
        if asset.symbol in stablecoin_symbols and asset.supply_value_usd > TOKEN_AMOUNT_DUST_EPSILON
    ]
    stable_collateral_usd = sum(asset.supply_value_usd for asset in stable_collateral_assets)
    if stable_collateral_usd <= TOKEN_AMOUNT_DUST_EPSILON or main_debt_asset.debt_amount <= 0:
        return None

    weighted_liquidation_threshold_numerator = sum(
        asset.supply_value_usd * asset.liquidation_threshold
        for asset in stable_collateral_assets
    )
    weighted_stable_collateral_liquidation_threshold = (
            weighted_liquidation_threshold_numerator / stable_collateral_usd
    )
    main_asset_price_usd = main_debt_asset.debt_value_usd / main_debt_asset.debt_amount
    return AaveSentinelStrategy(
        kind=AaveSentinelStrategyKind.SHORT,
        main_asset_symbol=main_debt_asset.symbol,
        main_asset_price_usd=main_asset_price_usd,
        liquidation_price_usd=compute_short_liquidation_price_usd(
            stable_collateral_usd=stable_collateral_usd,
            weighted_stable_collateral_liquidation_threshold=weighted_stable_collateral_liquidation_threshold,
            volatile_debt_token_amount=main_debt_asset.debt_amount,
        ),
        leverage=compute_strategy_leverage(
            collateral_usd=stable_collateral_usd,
            debt_usd=main_debt_asset.debt_value_usd,
        ),
        collateral_usd=stable_collateral_usd,
        debt_usd=main_debt_asset.debt_value_usd,
    )


def _resolve_long_strategy(
        detected_assets: list[AaveSentinelAssetSnapshot],
        stablecoin_symbols: frozenset[str],
) -> Optional[AaveSentinelStrategy]:
    stable_debt_usd = sum(
        asset.debt_value_usd
        for asset in detected_assets
        if asset.symbol in stablecoin_symbols and asset.debt_value_usd > TOKEN_AMOUNT_DUST_EPSILON
    )
    volatile_collateral_assets = [
        asset
        for asset in detected_assets
        if asset.symbol not in stablecoin_symbols and asset.supply_amount > TOKEN_AMOUNT_DUST_EPSILON
    ]
    if not volatile_collateral_assets:
        return None

    main_collateral_asset = max(
        volatile_collateral_assets,
        key=lambda asset_snapshot: asset_snapshot.supply_value_usd,
    )
    if main_collateral_asset.supply_amount <= 0:
        return None

    main_asset_price_usd = main_collateral_asset.supply_value_usd / main_collateral_asset.supply_amount
    return AaveSentinelStrategy(
        kind=AaveSentinelStrategyKind.LONG,
        main_asset_symbol=main_collateral_asset.symbol,
        main_asset_price_usd=main_asset_price_usd,
        liquidation_price_usd=compute_long_liquidation_price_usd(
            stable_debt_usd=stable_debt_usd,
            volatile_collateral_token_amount=main_collateral_asset.supply_amount,
            volatile_collateral_liquidation_threshold=main_collateral_asset.liquidation_threshold,
        ),
        leverage=compute_strategy_leverage(
            collateral_usd=main_collateral_asset.supply_value_usd,
            debt_usd=stable_debt_usd,
        ),
        collateral_usd=main_collateral_asset.supply_value_usd,
        debt_usd=stable_debt_usd,
    )
