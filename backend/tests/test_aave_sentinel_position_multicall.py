from __future__ import annotations

from eth_abi import encode

from src.core.aavesentinel.aave_sentinel_constants import WAVAX_CONTRACT_ADDRESS
from src.core.aavesentinel.aave_sentinel_structures import AaveSentinelReserveAsset
from src.core.aavesentinel.position.aave_sentinel_position_snapshot_service import (
    _POSITION_MULTICALL_CALLS_PER_RESERVE,
    build_asset_snapshots_from_multicall_results,
)
from src.integrations.aave.aave_abis import AAVE_RESERVE_DATA_ABI_TYPES
from src.integrations.blockchain.evm.blockchain_evm_multicall_reader import BlockchainEvmMulticallResult


def _uint256_result(value: int, is_success: bool = True) -> BlockchainEvmMulticallResult:
    return BlockchainEvmMulticallResult(
        is_success=is_success,
        return_data=encode(["uint256"], [value]) if is_success else b"",
    )


def _reserve_data_result(liquidation_threshold_basis_points: int) -> BlockchainEvmMulticallResult:
    configuration_bitmap = liquidation_threshold_basis_points << 16
    encoded_reserve_data = encode(
        AAVE_RESERVE_DATA_ABI_TYPES,
        [
            configuration_bitmap,
            10 ** 27,
            0,
            10 ** 27,
            0,
            0,
            0,
            1,
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000002",
            "0x0000000000000000000000000000000000000003",
            "0x0000000000000000000000000000000000000004",
            0,
            0,
            0,
        ],
    )
    return BlockchainEvmMulticallResult(is_success=True, return_data=encoded_reserve_data)


def _reserve_asset(symbol: str, underlying_address: str, decimal_count: int) -> AaveSentinelReserveAsset:
    return AaveSentinelReserveAsset(
        underlying_address=underlying_address.lower(),
        symbol=symbol,
        decimal_count=decimal_count,
        requires_euro_conversion=False,
        a_token_address="0x00000000000000000000000000000000000000a1",
        stable_debt_token_address="0x00000000000000000000000000000000000000a2",
        variable_debt_token_address="0x00000000000000000000000000000000000000a3",
    )


def _reserve_results(
        supply_raw: int,
        debt_raw: int,
        wallet_raw: int,
        price_raw: int,
        price_success: bool = True,
) -> list[BlockchainEvmMulticallResult]:
    return [
        _uint256_result(supply_raw),
        _uint256_result(debt_raw),
        _uint256_result(wallet_raw),
        _uint256_result(price_raw, is_success=price_success),
        _reserve_data_result(8000),
    ]


def test_position_multicall_decodes_balances_adds_native_wavax_and_skips_inactive_reserves() -> None:
    usdc_asset = _reserve_asset("USDC", "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e", 6)
    wavax_asset = _reserve_asset("WAVAX", WAVAX_CONTRACT_ADDRESS, 18)
    btc_asset = _reserve_asset("BTC.b", "0x152b9d0fdc40c096757f570a51e494bd4b943e50", 8)
    reserve_results: list[BlockchainEvmMulticallResult] = []
    reserve_results.extend(_reserve_results(supply_raw=0, debt_raw=0, wallet_raw=0, price_raw=10 ** 8))
    reserve_results.extend(_reserve_results(supply_raw=0, debt_raw=0, wallet_raw=0, price_raw=10 ** 8))
    reserve_results.extend(_reserve_results(supply_raw=150_000_000, debt_raw=0, wallet_raw=0, price_raw=2 * 10 ** 8))
    assert len(reserve_results) == 3 * _POSITION_MULTICALL_CALLS_PER_RESERVE

    asset_snapshots = build_asset_snapshots_from_multicall_results(
        reserve_assets=[usdc_asset, wavax_asset, btc_asset],
        reserve_multicall_results=reserve_results,
        native_balance_raw=10 ** 18,
    )

    assert [asset_snapshot.symbol for asset_snapshot in asset_snapshots] == ["BTC.b", "WAVAX"]
    btc_snapshot = asset_snapshots[0]
    assert btc_snapshot.supply_amount == 1.5
    assert btc_snapshot.supply_value_usd == 3.0
    assert btc_snapshot.liquidation_threshold == 0.8
    wavax_snapshot = asset_snapshots[1]
    assert wavax_snapshot.wallet_amount == 1.0
    assert wavax_snapshot.wallet_value_usd == 1.0


def test_position_multicall_skips_a_reserve_when_the_price_call_fails() -> None:
    usdc_asset = _reserve_asset("USDC", "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e", 6)
    reserve_results = _reserve_results(
        supply_raw=1_000_000,
        debt_raw=0,
        wallet_raw=0,
        price_raw=10 ** 8,
        price_success=False,
    )

    asset_snapshots = build_asset_snapshots_from_multicall_results(
        reserve_assets=[usdc_asset],
        reserve_multicall_results=reserve_results,
        native_balance_raw=None,
    )

    assert asset_snapshots == []
