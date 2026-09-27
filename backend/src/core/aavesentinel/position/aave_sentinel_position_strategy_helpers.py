from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAccountLiquidationPrice,
    AaveSentinelAssetSnapshot,
    AaveSentinelLiquidationDirection,
    AaveSentinelReserveRegistry,
    AaveSentinelStrategy,
    AaveSentinelStrategyKind,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_aave_net_worth_usd,
    compute_account_liquidation_price_usd,
    compute_account_notional_leverage,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    resolve_stablecoin_symbols,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def resolve_active_strategies(
        detected_assets: list[AaveSentinelAssetSnapshot],
        reserve_registry: AaveSentinelReserveRegistry,
) -> list[AaveSentinelStrategy]:
    stablecoin_symbols = resolve_stablecoin_symbols(reserve_registry=reserve_registry)
    aave_net_worth_usd: float = _compute_detected_assets_aave_net_worth_usd(
        detected_assets=detected_assets,
    )
    active_strategies: list[AaveSentinelStrategy] = []

    short_strategy = _resolve_short_strategy(
        detected_assets=detected_assets,
        stablecoin_symbols=stablecoin_symbols,
        aave_net_worth_usd=aave_net_worth_usd,
    )
    if short_strategy is not None:
        active_strategies.append(short_strategy)

    long_strategy = _resolve_long_strategy(
        detected_assets=detected_assets,
        stablecoin_symbols=stablecoin_symbols,
        aave_net_worth_usd=aave_net_worth_usd,
    )
    if long_strategy is not None:
        active_strategies.append(long_strategy)

    return active_strategies


def _compute_detected_assets_aave_net_worth_usd(
        detected_assets: list[AaveSentinelAssetSnapshot],
) -> float:
    total_collateral_usd: float = sum(asset.supply_value_usd for asset in detected_assets)
    total_debt_usd: float = sum(asset.debt_value_usd for asset in detected_assets)
    return compute_aave_net_worth_usd(
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
    )


def _resolve_account_liquidation_price_for_main_asset(
        detected_assets: list[AaveSentinelAssetSnapshot],
        main_asset_symbol: str,
) -> AaveSentinelAccountLiquidationPrice:
    main_asset: Optional[AaveSentinelAssetSnapshot] = None
    other_collateral_liquidation_capacity_usd: float = 0.0
    other_debt_usd: float = 0.0
    for asset in detected_assets:
        if asset.symbol == main_asset_symbol:
            main_asset = asset
            continue
        other_collateral_liquidation_capacity_usd += (
                asset.supply_value_usd * asset.liquidation_threshold
        )
        other_debt_usd += asset.debt_value_usd
    if main_asset is None:
        return AaveSentinelAccountLiquidationPrice(
            liquidation_price_usd=0.0,
            liquidation_direction=None,
        )
    return compute_account_liquidation_price_usd(
        main_asset_supply_token_amount=main_asset.supply_amount,
        main_asset_supply_liquidation_threshold=main_asset.liquidation_threshold,
        main_asset_debt_token_amount=main_asset.debt_amount,
        other_collateral_liquidation_capacity_usd=other_collateral_liquidation_capacity_usd,
        other_debt_usd=other_debt_usd,
    )


def _assign_account_liquidation_price_to_strategy(
        account_liquidation_price: AaveSentinelAccountLiquidationPrice,
        strategy_kind: AaveSentinelStrategyKind,
) -> AaveSentinelAccountLiquidationPrice:
    if (
            strategy_kind == AaveSentinelStrategyKind.SHORT
            and account_liquidation_price.liquidation_direction == AaveSentinelLiquidationDirection.UPSIDE
    ):
        return account_liquidation_price
    if (
            strategy_kind == AaveSentinelStrategyKind.LONG
            and account_liquidation_price.liquidation_direction == AaveSentinelLiquidationDirection.DOWNSIDE
    ):
        return account_liquidation_price
    return AaveSentinelAccountLiquidationPrice(
        liquidation_price_usd=0.0,
        liquidation_direction=None,
    )


def _resolve_short_strategy(
        detected_assets: list[AaveSentinelAssetSnapshot],
        stablecoin_symbols: frozenset[str],
        aave_net_worth_usd: float,
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

    main_asset_price_usd = main_debt_asset.debt_value_usd / main_debt_asset.debt_amount
    assigned_liquidation_price = _assign_account_liquidation_price_to_strategy(
        account_liquidation_price=_resolve_account_liquidation_price_for_main_asset(
            detected_assets=detected_assets,
            main_asset_symbol=main_debt_asset.symbol,
        ),
        strategy_kind=AaveSentinelStrategyKind.SHORT,
    )
    strategy_leverage: float = compute_account_notional_leverage(
        notional_usd=main_debt_asset.debt_value_usd,
        aave_net_worth_usd=aave_net_worth_usd,
    )
    assigned_liquidation_direction_label: Optional[str] = None
    if assigned_liquidation_price.liquidation_direction is not None:
        assigned_liquidation_direction_label = assigned_liquidation_price.liquidation_direction.value
    logger.debug(
        "[AAVESENTINEL][STRATEGY] kind=%s asset=%s leverage=%0.4f liquidation_price_usd=%0.2f direction=%s",
        AaveSentinelStrategyKind.SHORT.value,
        main_debt_asset.symbol,
        strategy_leverage,
        assigned_liquidation_price.liquidation_price_usd,
        assigned_liquidation_direction_label,
    )
    return AaveSentinelStrategy(
        kind=AaveSentinelStrategyKind.SHORT,
        main_asset_symbol=main_debt_asset.symbol,
        main_asset_price_usd=main_asset_price_usd,
        liquidation_price_usd=assigned_liquidation_price.liquidation_price_usd,
        leverage=strategy_leverage,
        collateral_usd=stable_collateral_usd,
        debt_usd=main_debt_asset.debt_value_usd,
        liquidation_direction=assigned_liquidation_price.liquidation_direction,
    )


def _resolve_long_strategy(
        detected_assets: list[AaveSentinelAssetSnapshot],
        stablecoin_symbols: frozenset[str],
        aave_net_worth_usd: float,
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
    assigned_liquidation_price = _assign_account_liquidation_price_to_strategy(
        account_liquidation_price=_resolve_account_liquidation_price_for_main_asset(
            detected_assets=detected_assets,
            main_asset_symbol=main_collateral_asset.symbol,
        ),
        strategy_kind=AaveSentinelStrategyKind.LONG,
    )
    strategy_leverage: float = compute_account_notional_leverage(
        notional_usd=main_collateral_asset.supply_value_usd,
        aave_net_worth_usd=aave_net_worth_usd,
    )
    assigned_liquidation_direction_label: Optional[str] = None
    if assigned_liquidation_price.liquidation_direction is not None:
        assigned_liquidation_direction_label = assigned_liquidation_price.liquidation_direction.value
    logger.debug(
        "[AAVESENTINEL][STRATEGY] kind=%s asset=%s leverage=%0.4f liquidation_price_usd=%0.2f direction=%s",
        AaveSentinelStrategyKind.LONG.value,
        main_collateral_asset.symbol,
        strategy_leverage,
        assigned_liquidation_price.liquidation_price_usd,
        assigned_liquidation_direction_label,
    )
    return AaveSentinelStrategy(
        kind=AaveSentinelStrategyKind.LONG,
        main_asset_symbol=main_collateral_asset.symbol,
        main_asset_price_usd=main_asset_price_usd,
        liquidation_price_usd=assigned_liquidation_price.liquidation_price_usd,
        leverage=strategy_leverage,
        collateral_usd=main_collateral_asset.supply_value_usd,
        debt_usd=stable_debt_usd,
        liquidation_direction=assigned_liquidation_price.liquidation_direction,
    )
