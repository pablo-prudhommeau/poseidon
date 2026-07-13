from __future__ import annotations

import pytest

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelErc20TransferFlow,
    AaveSentinelErc20TransferFlowRecord,
    AaveSentinelUniversalLedgerEntry,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_latent_profit_and_loss_usd,
    is_pure_capital_inflow_transaction,
    is_pure_capital_outflow_transaction,
    ledger_entry_has_net_native_receipt,
)


def test_compute_latent_profit_and_loss_usd_matches_preprod_snapshot_scenario() -> None:
    latent_profit_and_loss_usd = compute_latent_profit_and_loss_usd(
        total_equity_usd=11.85,
        net_capital_deployed_usd=11.87,
    )

    assert latent_profit_and_loss_usd == pytest.approx(-0.02)


def test_is_pure_capital_outflow_allows_withdrawal_when_only_gas_is_spent() -> None:
    ledger_entry = AaveSentinelUniversalLedgerEntry(
        transaction_hash="0xgasout",
        native_sent_amount=0.02,
        native_received_amount=0.0,
    )

    assert not ledger_entry_has_net_native_receipt(ledger_entry)
    assert is_pure_capital_outflow_transaction(ledger_entry)


def test_is_pure_capital_outflow_blocks_when_native_is_received() -> None:
    ledger_entry = AaveSentinelUniversalLedgerEntry(
        transaction_hash="0xswapnative",
        native_sent_amount=0.01,
        native_received_amount=0.50,
    )

    assert ledger_entry_has_net_native_receipt(ledger_entry)
    assert not is_pure_capital_outflow_transaction(ledger_entry)


def test_is_pure_capital_inflow_blocks_when_wallet_sent_erc20() -> None:
    ledger_entry = AaveSentinelUniversalLedgerEntry(
        transaction_hash="0xsupply",
        erc20_transfer_flows=[
            AaveSentinelErc20TransferFlowRecord(
                contract_address="0xusdc",
                transfer_flow=AaveSentinelErc20TransferFlow(
                    incoming_amount=0.0,
                    outgoing_amount=100.0,
                ),
            ),
            AaveSentinelErc20TransferFlowRecord(
                contract_address="0xausdc",
                transfer_flow=AaveSentinelErc20TransferFlow(
                    incoming_amount=100.0,
                    outgoing_amount=0.0,
                ),
            ),
        ],
    )

    assert not is_pure_capital_inflow_transaction(ledger_entry)
