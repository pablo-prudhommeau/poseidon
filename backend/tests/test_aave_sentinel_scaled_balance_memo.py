from __future__ import annotations

import asyncio

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelReserveAsset,
    AaveSentinelReserveRegistry,
    AaveSentinelScaledBalanceMemoEntry,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_scaled_balance_helpers import (
    fetch_scaled_balances_at_block_with_memo,
)
from src.integrations.aave.aave_structures import (
    AaveScaledBalanceBatchRequest,
    AaveScaledBalanceSnapshot,
)


class _CountingProtocolReader:
    def __init__(self, scaled_supply_balance: float) -> None:
        self.call_count: int = 0
        self._scaled_supply_balance: float = scaled_supply_balance

    async def fetch_scaled_balances_at_block_batch(
            self,
            wallet_address: str,
            scaled_balance_batch_requests: list[AaveScaledBalanceBatchRequest],
            block_number: int,
    ) -> list[AaveScaledBalanceSnapshot]:
        self.call_count += 1
        return [
            AaveScaledBalanceSnapshot(
                underlying_address=scaled_balance_batch_requests[0].underlying_address.lower(),
                scaled_supply_balance=self._scaled_supply_balance,
                scaled_debt_balance=0.0,
            ),
        ]


def _reserve_registry() -> AaveSentinelReserveRegistry:
    return AaveSentinelReserveRegistry(
        reserve_assets=(
            AaveSentinelReserveAsset(
                underlying_address="0x0000000000000000000000000000000000000002",
                symbol="USDC",
                decimal_count=6,
                requires_euro_conversion=False,
                a_token_address="0x0000000000000000000000000000000000000003",
                stable_debt_token_address="0x0000000000000000000000000000000000000004",
                variable_debt_token_address="0x0000000000000000000000000000000000000005",
            ),
        ),
    )


def test_historical_scaled_balances_are_not_fetched_again_on_the_same_block() -> None:
    protocol_reader = _CountingProtocolReader(scaled_supply_balance=1.5)
    memo_entries: list[AaveSentinelScaledBalanceMemoEntry] = []
    reserve_registry = _reserve_registry()

    async def run_test() -> None:
        first_balances = await fetch_scaled_balances_at_block_with_memo(
            aave_protocol_reader=protocol_reader,
            scaled_balance_memo_entries=memo_entries,
            reserve_registry=reserve_registry,
            wallet_address="0x0000000000000000000000000000000000000001",
            underlying_addresses=["0x0000000000000000000000000000000000000002"],
            block_number=100,
            refresh_from_chain=False,
        )
        second_balances = await fetch_scaled_balances_at_block_with_memo(
            aave_protocol_reader=protocol_reader,
            scaled_balance_memo_entries=memo_entries,
            reserve_registry=reserve_registry,
            wallet_address="0x0000000000000000000000000000000000000001",
            underlying_addresses=["0x0000000000000000000000000000000000000002"],
            block_number=100,
            refresh_from_chain=False,
        )
        latest_balances = await fetch_scaled_balances_at_block_with_memo(
            aave_protocol_reader=protocol_reader,
            scaled_balance_memo_entries=memo_entries,
            reserve_registry=reserve_registry,
            wallet_address="0x0000000000000000000000000000000000000001",
            underlying_addresses=["0x0000000000000000000000000000000000000002"],
            block_number=100,
            refresh_from_chain=True,
        )
        assert first_balances is not None and first_balances[0].scaled_supply_balance == 1.5
        assert second_balances is not None and second_balances[0].scaled_supply_balance == 1.5
        assert latest_balances is not None
        assert protocol_reader.call_count == 2

    asyncio.run(run_test())
