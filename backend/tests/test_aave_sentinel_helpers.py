from __future__ import annotations

import pytest

from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    aggregate_capital_flow_summary,
    collect_pure_capital_flow_events,
    convert_raw_capital_flow_events_to_classified_flows,
    is_fiat_stablecoin_symbol,
    resolve_asset_symbol_for_contract,
    resolve_stablecoin_symbols,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_ledger_helpers import (
    build_universal_ledger,
)
from src.core.aavesentinel.aave_sentinel_constants import WAVAX_CONTRACT_ADDRESS
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowDirection,
    AaveSentinelCapitalFlowValuationContext,
    AaveSentinelErc20TransferFlow,
    AaveSentinelErc20TransferFlowRecord,
    AaveSentinelReserveAsset,
    AaveSentinelReserveRegistry,
    AaveSentinelUniversalLedger,
    AaveSentinelUniversalLedgerEntry,
)
from src.integrations.routescan.routescan_structures import (
    RoutescanInternalTransactionRecord,
    RoutescanNormalTransactionRecord,
    RoutescanTokenTransactionRecord,
)

WALLET_ADDRESS = "0x1111111111111111111111111111111111111111"
USDC_CONTRACT_ADDRESS = "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"
EURC_CONTRACT_ADDRESS = "0xc891eb4cbdeff6e073e859e987815ed1505c2acd"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def build_test_reserve_registry(
        *,
        include_wavax: bool = True,
        debt_token_address: str | None = None,
) -> AaveSentinelReserveRegistry:
    reserve_assets: list[AaveSentinelReserveAsset] = [
        AaveSentinelReserveAsset(
            underlying_address=USDC_CONTRACT_ADDRESS,
            symbol="USDC",
            decimal_count=6,
            requires_euro_conversion=False,
            a_token_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            stable_debt_token_address=ZERO_ADDRESS,
            variable_debt_token_address=ZERO_ADDRESS,
        ),
        AaveSentinelReserveAsset(
            underlying_address=EURC_CONTRACT_ADDRESS,
            symbol="EURC",
            decimal_count=6,
            requires_euro_conversion=True,
            a_token_address="0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            stable_debt_token_address=ZERO_ADDRESS,
            variable_debt_token_address=ZERO_ADDRESS,
        ),
    ]
    if include_wavax:
        reserve_assets.append(
            AaveSentinelReserveAsset(
                underlying_address=WAVAX_CONTRACT_ADDRESS,
                symbol="WAVAX",
                decimal_count=18,
                requires_euro_conversion=False,
                a_token_address="0xcccccccccccccccccccccccccccccccccccccccc",
                stable_debt_token_address=ZERO_ADDRESS,
                variable_debt_token_address=ZERO_ADDRESS,
            ),
        )
    if debt_token_address is not None:
        reserve_assets.append(
            AaveSentinelReserveAsset(
                underlying_address="0xbbbb000000000000000000000000000000000001",
                symbol="BTC.b",
                decimal_count=8,
                requires_euro_conversion=False,
                a_token_address="0xdddddddddddddddddddddddddddddddddddddddd",
                stable_debt_token_address=ZERO_ADDRESS,
                variable_debt_token_address=debt_token_address,
            ),
        )
    return AaveSentinelReserveRegistry(reserve_assets=tuple(reserve_assets))


class FixedCapitalFlowUsdValuationResolver:
    def __init__(
            self,
            volatile_asset_price_usd: float = 1.0,
            euro_exchange_rate: float = 1.0,
            asset_price_usd_by_symbol: dict[str, float] | None = None,
    ) -> None:
        self._volatile_asset_price_usd = volatile_asset_price_usd
        self._euro_exchange_rate = euro_exchange_rate
        self._asset_price_usd_by_symbol = asset_price_usd_by_symbol or {}

    def resolve_amount_usd(self, valuation_context: AaveSentinelCapitalFlowValuationContext) -> float:
        if valuation_context.requires_euro_conversion:
            return valuation_context.token_amount * self._euro_exchange_rate
        asset_price_usd = self._asset_price_usd_by_symbol.get(
            valuation_context.asset_symbol,
            self._volatile_asset_price_usd,
        )
        return valuation_context.token_amount * asset_price_usd


def _ledger_entry_with_erc20_flow(
        transaction_hash: str,
        contract_address: str,
        incoming_amount: float,
        outgoing_amount: float,
        block_number: int = 0,
        timestamp_seconds: int = 0,
) -> AaveSentinelUniversalLedgerEntry:
    return AaveSentinelUniversalLedgerEntry(
        transaction_hash=transaction_hash,
        block_number=block_number,
        timestamp_seconds=timestamp_seconds,
        erc20_transfer_flows=[
            AaveSentinelErc20TransferFlowRecord(
                contract_address=contract_address.lower(),
                transfer_flow=AaveSentinelErc20TransferFlow(
                    incoming_amount=incoming_amount,
                    outgoing_amount=outgoing_amount,
                ),
            ),
        ],
    )


def _collect_flow_events_from_ledger_entries(
        ledger_entries: list[AaveSentinelUniversalLedgerEntry],
        reserve_registry: AaveSentinelReserveRegistry | None = None,
) -> list:
    universal_ledger = AaveSentinelUniversalLedger(entries=ledger_entries)
    return collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=reserve_registry or build_test_reserve_registry(),
    )


def test_is_fiat_stablecoin_symbol_detects_usd_and_euro_stables() -> None:
    assert is_fiat_stablecoin_symbol("USDC") is True
    assert is_fiat_stablecoin_symbol("EURC") is True
    assert is_fiat_stablecoin_symbol("WAVAX") is False


def test_resolve_asset_symbol_for_contract_uses_reserve_registry() -> None:
    reserve_registry = build_test_reserve_registry()

    assert resolve_asset_symbol_for_contract(
        reserve_registry=reserve_registry,
        contract_address=WAVAX_CONTRACT_ADDRESS,
    ) == "WAVAX"
    assert resolve_asset_symbol_for_contract(
        reserve_registry=reserve_registry,
        contract_address="0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    ) == "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def test_resolve_stablecoin_symbols_uses_reserve_registry() -> None:
    stablecoin_symbols = resolve_stablecoin_symbols(reserve_registry=build_test_reserve_registry())

    assert "USDC" in stablecoin_symbols
    assert "EURC" in stablecoin_symbols
    assert "WAVAX" not in stablecoin_symbols


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

    universal_ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )

    raw_flow_events = collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=build_test_reserve_registry(include_wavax=False),
    )

    assert len(raw_flow_events) == 1
    assert raw_flow_events[0].direction == AaveSentinelCapitalFlowDirection.INFLOW
    assert raw_flow_events[0].token_amount == 1000.0
    assert raw_flow_events[0].requires_euro_conversion is False


def test_wavax_jumper_inflow_is_classified() -> None:
    token_transactions = [
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xjumper001",
            "blockNumber": "110",
            "timeStamp": "1700000050",
            "from": "0xjumper00000000000000000000000000000001",
            "to": WALLET_ADDRESS,
            "contractAddress": WAVAX_CONTRACT_ADDRESS,
            "tokenDecimal": "18",
            "value": "293000000000000000",
        }),
    ]

    universal_ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )

    raw_flow_events = collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=build_test_reserve_registry(),
    )

    assert len(raw_flow_events) == 1
    assert raw_flow_events[0].direction == AaveSentinelCapitalFlowDirection.INFLOW
    assert raw_flow_events[0].asset_symbol == "WAVAX"
    assert raw_flow_events[0].token_amount == pytest.approx(0.293)


def test_internal_native_avax_inflow_inherits_block_metadata() -> None:
    internal_transactions = [
        RoutescanInternalTransactionRecord.model_validate({
            "hash": "0xinternalavax001",
            "blockNumber": "90200000",
            "timeStamp": "1700000050",
            "from": "0xbridge0000000000000000000000000000000001",
            "to": WALLET_ADDRESS,
            "value": "293000000000000000",
        }),
    ]

    universal_ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=internal_transactions,
        token_transactions=[],
    )

    raw_flow_events = collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=build_test_reserve_registry(),
    )

    assert len(raw_flow_events) == 1
    assert raw_flow_events[0].asset_symbol == "AVAX"
    assert raw_flow_events[0].block_number == 90200000
    assert raw_flow_events[0].timestamp_seconds == 1700000050


def test_aave_supply_is_excluded_when_atoken_received() -> None:
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

    universal_ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )

    raw_flow_events = collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=build_test_reserve_registry(include_wavax=False),
    )

    assert raw_flow_events == []


def test_swap_is_excluded_from_capital_flows() -> None:
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

    universal_ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=[],
        internal_transactions=[],
        token_transactions=token_transactions,
    )

    raw_flow_events = collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=build_test_reserve_registry(include_wavax=False),
    )

    assert raw_flow_events == []


def test_aave_borrow_mint_is_excluded_from_capital_flows() -> None:
    debt_token_address = "0xdddd000000000000000000000000000000000001"
    borrowed_asset_address = "0xbbbb000000000000000000000000000000000001"
    reserve_registry = build_test_reserve_registry(
        include_wavax=False,
        debt_token_address=debt_token_address,
    )

    ledger_entries = [
        AaveSentinelUniversalLedgerEntry(
            transaction_hash="0xborrow123",
            block_number=90239527,
            timestamp_seconds=1_783_980_500,
            erc20_transfer_flows=[
                AaveSentinelErc20TransferFlowRecord(
                    contract_address=debt_token_address,
                    transfer_flow=AaveSentinelErc20TransferFlow(
                        incoming_amount=0.00001,
                        outgoing_amount=0.0,
                    ),
                ),
                AaveSentinelErc20TransferFlowRecord(
                    contract_address=borrowed_asset_address,
                    transfer_flow=AaveSentinelErc20TransferFlow(
                        incoming_amount=0.00001,
                        outgoing_amount=0.0,
                    ),
                ),
            ],
        ),
    ]

    raw_flow_events = _collect_flow_events_from_ledger_entries(
        ledger_entries=ledger_entries,
        reserve_registry=reserve_registry,
    )

    assert raw_flow_events == []


def test_pure_usdc_outflow_with_gas_payment_is_classified() -> None:
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
    normal_transactions = [
        RoutescanNormalTransactionRecord.model_validate({
            "hash": "0xout999",
            "blockNumber": "103",
            "timeStamp": "1700000300",
            "from": WALLET_ADDRESS,
            "to": "0xexternal00000000000000000000000000000002",
            "value": "20000000000000000",
        }),
    ]

    universal_ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=normal_transactions,
        internal_transactions=[],
        token_transactions=token_transactions,
    )

    raw_flow_events = collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=build_test_reserve_registry(include_wavax=False),
    )

    assert len(raw_flow_events) == 1
    assert raw_flow_events[0].direction == AaveSentinelCapitalFlowDirection.OUTFLOW
    assert raw_flow_events[0].token_amount == 250.0


def test_usdc_outflow_is_excluded_when_native_avalanche_is_received() -> None:
    token_transactions = [
        RoutescanTokenTransactionRecord.model_validate({
            "hash": "0xswapnative",
            "blockNumber": "104",
            "timeStamp": "1700000400",
            "from": WALLET_ADDRESS,
            "to": "0xdexrouter00000000000000000000000000000001",
            "contractAddress": USDC_CONTRACT_ADDRESS,
            "tokenDecimal": "6",
            "value": "100000000",
        }),
    ]
    normal_transactions = [
        RoutescanNormalTransactionRecord.model_validate({
            "hash": "0xswapnative",
            "blockNumber": "104",
            "timeStamp": "1700000400",
            "from": "0xdexrouter00000000000000000000000000000001",
            "to": WALLET_ADDRESS,
            "value": "500000000000000000",
        }),
    ]

    universal_ledger = build_universal_ledger(
        wallet_address=WALLET_ADDRESS,
        normal_transactions=normal_transactions,
        internal_transactions=[],
        token_transactions=token_transactions,
    )

    raw_flow_events = collect_pure_capital_flow_events(
        universal_ledger=universal_ledger,
        reserve_registry=build_test_reserve_registry(include_wavax=False),
    )

    assert raw_flow_events == []


def test_eurc_conversion_uses_exchange_rate_resolver() -> None:
    raw_flow_events = _collect_flow_events_from_ledger_entries(
        ledger_entries=[
            _ledger_entry_with_erc20_flow(
                transaction_hash="0xeuro001",
                contract_address=EURC_CONTRACT_ADDRESS,
                incoming_amount=100.0,
                outgoing_amount=0.0,
                block_number=200,
                timestamp_seconds=1700000400,
            ),
        ],
    )

    classified_flows = convert_raw_capital_flow_events_to_classified_flows(
        raw_flow_events=raw_flow_events,
        valuation_resolver=FixedCapitalFlowUsdValuationResolver(euro_exchange_rate=1.10),
    )

    assert len(classified_flows) == 1
    assert classified_flows[0].amount_usd == pytest.approx(110.0)


def test_aggregate_capital_flow_summary_computes_net_capital() -> None:
    raw_flow_events = _collect_flow_events_from_ledger_entries(
        ledger_entries=[
            _ledger_entry_with_erc20_flow(
                transaction_hash="0xin",
                contract_address=USDC_CONTRACT_ADDRESS,
                incoming_amount=1000.0,
                outgoing_amount=0.0,
                block_number=1,
                timestamp_seconds=1,
            ),
            _ledger_entry_with_erc20_flow(
                transaction_hash="0xout",
                contract_address=USDC_CONTRACT_ADDRESS,
                incoming_amount=0.0,
                outgoing_amount=200.0,
                block_number=2,
                timestamp_seconds=2,
            ),
        ],
    )

    classified_flows = convert_raw_capital_flow_events_to_classified_flows(
        raw_flow_events=raw_flow_events,
        valuation_resolver=FixedCapitalFlowUsdValuationResolver(),
    )

    summary = aggregate_capital_flow_summary(
        classified_flows=classified_flows,
        is_available=True,
    )

    assert summary.total_inflow_usd == 1000.0
    assert summary.total_outflow_usd == 200.0
    assert summary.net_capital_deployed_usd == 800.0


def test_preprod_like_capital_net_includes_wavax_and_usdc() -> None:
    raw_flow_events = _collect_flow_events_from_ledger_entries(
        ledger_entries=[
            _ledger_entry_with_erc20_flow(
                transaction_hash="0xusdcin",
                contract_address=USDC_CONTRACT_ADDRESS,
                incoming_amount=9.99,
                outgoing_amount=0.0,
                block_number=10,
                timestamp_seconds=10,
            ),
            _ledger_entry_with_erc20_flow(
                transaction_hash="0xwavaxin",
                contract_address=WAVAX_CONTRACT_ADDRESS,
                incoming_amount=0.293,
                outgoing_amount=0.0,
                block_number=11,
                timestamp_seconds=11,
            ),
        ],
    )

    classified_flows = convert_raw_capital_flow_events_to_classified_flows(
        raw_flow_events=raw_flow_events,
        valuation_resolver=FixedCapitalFlowUsdValuationResolver(
            asset_price_usd_by_symbol={"USDC": 1.0},
            volatile_asset_price_usd=1.88 / 0.293,
        ),
    )
    summary = aggregate_capital_flow_summary(
        classified_flows=classified_flows,
        is_available=True,
    )

    assert summary.net_capital_deployed_usd == pytest.approx(11.87, rel=1e-3)
    latent_profit_and_loss = 11.85 - summary.net_capital_deployed_usd
    assert latent_profit_and_loss == pytest.approx(0.0, abs=0.05)
