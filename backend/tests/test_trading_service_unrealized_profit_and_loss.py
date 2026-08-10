from __future__ import annotations

from unittest.mock import MagicMock

from src.api.http.api_schemas import TradingTradePayload
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_service import compute_holdings_and_unrealized_totals
from src.integrations.blockchain.blockchain_price_structures import OnchainPricesByPairAddress
from src.persistence.models import PositionPhase, TradingPosition


def _build_open_position() -> TradingPosition:
    return TradingPosition(
        id=1,
        evaluation_id=10,
        token_symbol="TEST",
        blockchain_network="solana",
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
        open_quantity=100.0,
        current_quantity=100.0,
        entry_price=1.0,
        breakeven_arm_price=1.2,
        take_profit_price=1.5,
        stop_loss_price=0.8,
        initial_stop_loss_price=0.8,
        position_phase=PositionPhase.OPEN,
        opened_at=MagicMock(),
        updated_at=MagicMock(),
    )


def _build_buy_trade(*, transaction_fee: float) -> TradingTradePayload:
    return TradingTradePayload(
        id=1,
        evaluation_id=10,
        trade_side="BUY",
        token_symbol="TEST",
        blockchain_network=BlockchainNetwork.SOLANA,
        execution_price=1.0,
        execution_quantity=100.0,
        transaction_fee=transaction_fee,
        execution_status="LIVE",
        token_address="token-address",
        pair_address="pair-address",
        created_at="2026-06-07T12:00:00+02:00",
        dex_id="raydium",
        realized_profit_and_loss=None,
        transaction_hash="sig-buy",
        linked_position_id=1,
        evaluation_order_notional_value_usd=100.0,
    )


def test_compute_holdings_and_unrealized_totals_deducts_allocated_buy_swap_fees() -> None:
    position = _build_open_position()
    onchain_prices = MagicMock(spec=OnchainPricesByPairAddress)
    onchain_prices.try_resolve_price_usd_for_pair_address.return_value = 1.5

    holdings_without_fees, unrealized_without_fees = compute_holdings_and_unrealized_totals(
        [position],
        onchain_prices,
    )
    holdings_with_fees, unrealized_with_fees = compute_holdings_and_unrealized_totals(
        [position],
        onchain_prices,
        trades=[_build_buy_trade(transaction_fee=2.5)],
    )

    assert holdings_without_fees == 150.0
    assert unrealized_without_fees == 50.0
    assert holdings_with_fees == 150.0
    assert unrealized_with_fees == 47.5
