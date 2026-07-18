from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetPriceUsd,
    AaveSentinelReserveRegistry,
    AaveSentinelUniversalLedgerEntry,
    AaveSentinelWalletTokenBalance,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    resolve_reserve_asset_for_underlying,
    resolve_stablecoin_symbols,
)


def resolve_asset_price_usd(
        asset_price_usd_by_underlying: dict[str, float],
        underlying_address: str,
) -> Optional[float]:
    return asset_price_usd_by_underlying.get(underlying_address.lower())


def resolve_asset_price_usd_for_symbol(
        asset_prices_usd: list[AaveSentinelAssetPriceUsd],
        asset_symbol: Optional[str],
        reserve_registry: Optional[AaveSentinelReserveRegistry],
) -> float:
    if asset_symbol is None or reserve_registry is None:
        return 0.0
    for reserve_asset in reserve_registry.reserve_assets:
        if reserve_asset.symbol != asset_symbol:
            continue
        asset_price_usd = resolve_asset_price_usd_from_prices(
            asset_prices_usd=asset_prices_usd,
            underlying_address=reserve_asset.underlying_address,
        )
        if asset_price_usd is None:
            return 0.0
        return asset_price_usd
    return 0.0


def find_wallet_token_balance(
        wallet_token_balances: list[AaveSentinelWalletTokenBalance],
        underlying_address: str,
) -> Optional[AaveSentinelWalletTokenBalance]:
    normalized_underlying_address: str = underlying_address.lower()
    for wallet_token_balance in wallet_token_balances:
        if wallet_token_balance.underlying_address == normalized_underlying_address:
            return wallet_token_balance
    return None


def resolve_or_create_wallet_token_balance(
        wallet_token_balances: list[AaveSentinelWalletTokenBalance],
        underlying_address: str,
) -> AaveSentinelWalletTokenBalance:
    existing_wallet_token_balance = find_wallet_token_balance(
        wallet_token_balances=wallet_token_balances,
        underlying_address=underlying_address,
    )
    if existing_wallet_token_balance is not None:
        return existing_wallet_token_balance
    wallet_token_balance = AaveSentinelWalletTokenBalance(
        underlying_address=underlying_address.lower(),
        token_amount=0.0,
    )
    wallet_token_balances.append(wallet_token_balance)
    return wallet_token_balance


def resolve_asset_price_usd_from_prices(
        asset_prices_usd: list[AaveSentinelAssetPriceUsd],
        underlying_address: str,
) -> Optional[float]:
    normalized_underlying_address: str = underlying_address.lower()
    for asset_price_usd in asset_prices_usd:
        if asset_price_usd.underlying_address == normalized_underlying_address:
            return asset_price_usd.price_usd
    return None


def collect_wallet_underlying_addresses(
        wallet_token_balances: list[AaveSentinelWalletTokenBalance],
) -> list[str]:
    underlying_addresses: list[str] = []
    for wallet_token_balance in wallet_token_balances:
        if abs(wallet_token_balance.token_amount) < TOKEN_AMOUNT_DUST_EPSILON:
            continue
        underlying_addresses.append(wallet_token_balance.underlying_address)
    return underlying_addresses


def apply_reserve_underlying_wallet_transfers(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        reserve_registry: AaveSentinelReserveRegistry,
        wallet_token_balances: list[AaveSentinelWalletTokenBalance],
) -> None:
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        reserve_asset = resolve_reserve_asset_for_underlying(
            reserve_registry=reserve_registry,
            underlying_address=transfer_flow_record.contract_address,
        )
        if reserve_asset is None:
            continue
        net_token_amount = (
                transfer_flow_record.transfer_flow.incoming_amount
                - transfer_flow_record.transfer_flow.outgoing_amount
        )
        if abs(net_token_amount) < TOKEN_AMOUNT_DUST_EPSILON:
            continue
        wallet_token_balance = resolve_or_create_wallet_token_balance(
            wallet_token_balances=wallet_token_balances,
            underlying_address=reserve_asset.underlying_address,
        )
        wallet_token_balance.token_amount += net_token_amount


def compute_wallet_equity_usd(
        wallet_token_balances: list[AaveSentinelWalletTokenBalance],
        asset_prices_usd: list[AaveSentinelAssetPriceUsd],
        reserve_registry: AaveSentinelReserveRegistry,
) -> float:
    wallet_equity_usd: float = 0.0
    stablecoin_symbols = resolve_stablecoin_symbols(reserve_registry=reserve_registry)
    for wallet_token_balance in wallet_token_balances:
        if abs(wallet_token_balance.token_amount) < TOKEN_AMOUNT_DUST_EPSILON:
            continue
        asset_price_usd = resolve_asset_price_usd_from_prices(
            asset_prices_usd=asset_prices_usd,
            underlying_address=wallet_token_balance.underlying_address,
        )
        if asset_price_usd is None:
            reserve_asset = resolve_reserve_asset_for_underlying(
                reserve_registry=reserve_registry,
                underlying_address=wallet_token_balance.underlying_address,
            )
            if reserve_asset is None:
                continue
            if reserve_asset.symbol not in stablecoin_symbols:
                continue
            asset_price_usd = 1.0
        wallet_equity_usd += wallet_token_balance.token_amount * asset_price_usd
    return wallet_equity_usd


def build_asset_prices_usd(
        asset_price_usd_by_underlying: dict[str, float],
) -> list[AaveSentinelAssetPriceUsd]:
    asset_prices_usd: list[AaveSentinelAssetPriceUsd] = []
    for underlying_address, price_usd in asset_price_usd_by_underlying.items():
        asset_prices_usd.append(
            AaveSentinelAssetPriceUsd(
                underlying_address=underlying_address.lower(),
                price_usd=price_usd,
            )
        )
    return asset_prices_usd


def clone_wallet_token_balances(
        wallet_token_balances: list[AaveSentinelWalletTokenBalance],
) -> list[AaveSentinelWalletTokenBalance]:
    return [
        AaveSentinelWalletTokenBalance(
            underlying_address=wallet_token_balance.underlying_address,
            token_amount=wallet_token_balance.token_amount,
        )
        for wallet_token_balance in wallet_token_balances
    ]
