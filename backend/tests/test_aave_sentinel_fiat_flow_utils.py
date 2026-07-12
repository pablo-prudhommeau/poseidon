from __future__ import annotations

import pytest

from src.core.aavesentinel.aave_sentinel_fiat_flow_structures import (
    AaveSentinelErc20TransferFlow,
    AaveSentinelFiatFlowDirection,
    AaveSentinelTrackedStablecoin,
    AaveSentinelUniversalLedgerEntry,
)
from src.core.aavesentinel.aave_sentinel_fiat_flow_utils import (
    aggregate_fiat_flow_summary,
    build_universal_ledger,
    collect_pure_fiat_flow_events,
    convert_raw_fiat_flow_events_to_classified_flows,
)
from src.integrations.routescan.routescan_structures import (
    RoutescanInternalTransactionRecord,
    RoutescanNormalTransactionRecord,
    RoutescanTokenTransactionRecord,
)

WALLET_ADDRESS = "0x1111111111111111111111111111111111111111"
USDC_CONTRACT_ADDRESS = "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"


def test_pure_usdc_inflow_is_classified() -> None:
    token_transactions = [
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xabc123",
            "blockNumber": "100",
            "timeStamp": "1700000000",
            "from": "0xexternal00000000000000000000000000000001",
            "to": WALLET_ADDRESS,
            "contractAddress": USDC_CONTRACT_ADDRESS,
            "tokenDecimal": "6",
            "value": "1000000000",
        }),
    ]

    ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )
    tracked_stablecoins = [
        AaveSentinelTrackedStablecoin(
            symbol="USDC",
            contract_address=USDC_CONTRACT_ADDRESS,
            decimal_count=6,
        ),
    ]

    raw_flow_events = collect_pure_fiat_flow_events(
        ledger_by_transaction_hash=ledger,
        tracked_stablecoins=tracked_stablecoins,
    )

    assert len(raw_flow_events) == 1
    assert raw_flow_events[0].direction == AaveSentinelFiatFlowDirection.INFLOW
    assert raw_flow_events[0].token_amount == 1000.0


def test_aave_supply_is_excluded_from_outflow_when_atoken_received() -> None:
    token_transactions = [
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xdef456",
            "blockNumber": "101",
            "timeStamp": "1700000100",
            "from": WALLET_ADDRESS,
            "to": "0xaavepool00000000000000000000000000000001",
            "contractAddress": USDC_CONTRACT_ADDRESS,
            "tokenDecimal": "6",
            "value": "500000000",
        }),
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xdef456",
            "blockNumber": "101",
            "timeStamp": "1700000100",
            "from": "0x0000000000000000000000000000000000000000",
            "to": WALLET_ADDRESS,
            "contractAddress": "0xaUSDC000000000000000000000000000000001",
            "tokenDecimal": "6",
            "value": "500000000",
        }),
    ]

    ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )
    tracked_stablecoins = [
        AaveSentinelTrackedStablecoin(
            symbol="USDC",
            contract_address=USDC_CONTRACT_ADDRESS,
            decimal_count=6,
        ),
    ]

    raw_flow_events = collect_pure_fiat_flow_events(
        ledger_by_transaction_hash=ledger,
        tracked_stablecoins=tracked_stablecoins,
    )

    assert raw_flow_events == []


def test_swap_is_excluded_from_outflow() -> None:
    token_transactions = [
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xswap789",
            "blockNumber": "102",
            "timeStamp": "1700000200",
            "from": WALLET_ADDRESS,
            "to": "0xdexrouter00000000000000000000000000000001",
            "contractAddress": USDC_CONTRACT_ADDRESS,
            "tokenDecimal": "6",
            "value": "200000000",
        }),
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xswap789",
            "blockNumber": "102",
            "timeStamp": "1700000200",
            "from": "0xdexrouter00000000000000000000000000000001",
            "to": WALLET_ADDRESS,
            "contractAddress": "0x152b9d0fdc40c096757f570a51e494bd4b943e50",
            "tokenDecimal": "8",
            "value": "300000",
        }),
    ]

    ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )
    tracked_stablecoins = [
        AaveSentinelTrackedStablecoin(
            symbol="USDC",
            contract_address=USDC_CONTRACT_ADDRESS,
            decimal_count=6,
        ),
    ]

    raw_flow_events = collect_pure_fiat_flow_events(
        ledger_by_transaction_hash=ledger,
        tracked_stablecoins=tracked_stablecoins,
    )

    assert raw_flow_events == []


def test_pure_usdc_outflow_is_classified() -> None:
    token_transactions = [
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xout999",
            "blockNumber": "103",
            "timeStamp": "1700000300",
            "from": WALLET_ADDRESS,
            "to": "0xexternal00000000000000000000000000000002",
            "contractAddress": USDC_CONTRACT_ADDRESS,
            "tokenDecimal": "6",
            "value": "250000000",
        }),
    ]

    ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )
    tracked_stablecoins = [
        AaveSentinelTrackedStablecoin(
            symbol="USDC",
            contract_address=USDC_CONTRACT_ADDRESS,
            decimal_count=6,
        ),
    ]

    raw_flow_events = collect_pure_fiat_flow_events(
        ledger_by_transaction_hash=ledger,
        tracked_stablecoins=tracked_stablecoins,
    )

    assert len(raw_flow_events) == 1
    assert raw_flow_events[0].direction == AaveSentinelFiatFlowDirection.OUTFLOW
    assert raw_flow_events[0].token_amount == 250.0


def test_eurc_conversion_uses_exchange_rate_resolver() -> None:
    raw_flow_events = collect_pure_fiat_flow_events(
        ledger_by_transaction_hash={
            "0xeuro001": AaveSentinelUniversalLedgerEntry(
                transaction_hash="0xeuro001",
                block_number=200,
                timestamp_seconds=1700000400,
                erc20_transfer_flows_by_contract={
                    "0xc891eb4cbdeff6e073e859e987815ed1505c2acd": AaveSentinelErc20TransferFlow(
                        incoming_amount=100.0,
                        outgoing_amount=0.0,
                    ),
                },
            ),
        },
        tracked_stablecoins=[
            AaveSentinelTrackedStablecoin(
                symbol="EURC",
                contract_address="0xc891eb4cbdeff6e073e859e987815ed1505c2acd",
                decimal_count=6,
                requires_euro_conversion=True,
            ),
        ],
    )

    classified_flows = convert_raw_fiat_flow_events_to_classified_flows(
        raw_flow_events=raw_flow_events,
        resolve_euro_to_usd_exchange_rate=lambda block_number, timestamp_seconds: 1.10,
    )

    assert len(classified_flows) == 1
    assert classified_flows[0].amount_usd == pytest.approx(110.0)


def test_aggregate_fiat_flow_summary_computes_net_capital() -> None:
    classified_flows = convert_raw_fiat_flow_events_to_classified_flows(
        raw_flow_events=collect_pure_fiat_flow_events(
            ledger_by_transaction_hash={
                "0xin": AaveSentinelUniversalLedgerEntry(
                    transaction_hash="0xin",
                    block_number=1,
                    timestamp_seconds=1,
                    erc20_transfer_flows_by_contract={
                        USDC_CONTRACT_ADDRESS: AaveSentinelErc20TransferFlow(
                            incoming_amount=1000.0,
                            outgoing_amount=0.0,
                        ),
                    },
                ),
                "0xout": AaveSentinelUniversalLedgerEntry(
                    transaction_hash="0xout",
                    block_number=2,
                    timestamp_seconds=2,
                    erc20_transfer_flows_by_contract={
                        USDC_CONTRACT_ADDRESS: AaveSentinelErc20TransferFlow(
                            incoming_amount=0.0,
                            outgoing_amount=200.0,
                        ),
                    },
                ),
            },
            tracked_stablecoins=[
                AaveSentinelTrackedStablecoin(
                    symbol="USDC",
                    contract_address=USDC_CONTRACT_ADDRESS,
                    decimal_count=6,
                ),
            ],
        ),
        resolve_euro_to_usd_exchange_rate=lambda block_number, timestamp_seconds: 1.0,
    )

    summary = aggregate_fiat_flow_summary(
        classified_flows=classified_flows,
        tracked_stablecoins=[
            AaveSentinelTrackedStablecoin(
                symbol="USDC",
                contract_address=USDC_CONTRACT_ADDRESS,
                decimal_count=6,
            ),
        ],
        is_available=True,
    )

    assert summary.total_inflow_usd == 1000.0
    assert summary.total_outflow_usd == 200.0
    assert summary.net_capital_deployed_usd == 800.0
