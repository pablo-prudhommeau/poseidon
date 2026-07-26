from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.execution.evm.trading_execution_evm_service import (
    build_evm_buy_route,
    build_evm_sell_route,
    cap_evm_sell_quantity_to_wallet_balance,
    resolve_evm_sell_token_decimals,
    run_evm_live_buy_blocking,
    run_evm_live_sell_blocking,
)
from src.core.trading.execution.trading_execution_structures import TradingLiveSellExecutionOutcome
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute


class TradingExecutionEvmHandler:
    def __init__(self, blockchain_network: BlockchainNetwork) -> None:
        self._blockchain_network = blockchain_network

    def blockchain_network(self) -> BlockchainNetwork:
        return self._blockchain_network

    def build_buy_route(self, candidate: TradingCandidate, order_notional_usd: float) -> BlockchainExecutionRoute:
        return build_evm_buy_route(
            blockchain_network=self._blockchain_network,
            candidate=candidate,
            order_notional_usd=order_notional_usd,
        )

    def build_sell_route(self, token_mint: str, token_quantity: float, token_decimals: int) -> BlockchainExecutionRoute:
        return build_evm_sell_route(
            blockchain_network=self._blockchain_network,
            token_address=token_mint,
            token_quantity=token_quantity,
            token_decimals=token_decimals,
        )

    def resolve_sell_token_decimals(self, token_address: str) -> int:
        return resolve_evm_sell_token_decimals(self._blockchain_network, token_address)

    def cap_sell_quantity_to_wallet_balance(
            self,
            token_address: str,
            sell_quantity: float,
            token_decimals: int,
    ) -> float:
        return cap_evm_sell_quantity_to_wallet_balance(
            blockchain_network=self._blockchain_network,
            token_address=token_address,
            sell_quantity=sell_quantity,
            token_decimals=token_decimals,
        )

    def run_live_buy_blocking(
            self,
            token: Token,
            quantity: float,
            price_usd: float,
            stop_loss_usd: float,
            take_profit_tp1_usd: float,
            take_profit_tp2_usd: float,
            execution_route: BlockchainExecutionRoute,
            origin_evaluation_id: int,
    ) -> bool:
        return run_evm_live_buy_blocking(
            blockchain_network=self._blockchain_network,
            token=token,
            quantity=quantity,
            price_usd=price_usd,
            stop_loss_usd=stop_loss_usd,
            take_profit_tp1_usd=take_profit_tp1_usd,
            take_profit_tp2_usd=take_profit_tp2_usd,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        )

    def run_live_sell_blocking(
            self,
            token_symbol: str,
            token_address: str,
            pair_address: str,
            dex_id: str,
            quantity: float,
            execution_price: float,
            execution_route: BlockchainExecutionRoute,
            origin_evaluation_id: int,
    ) -> TradingLiveSellExecutionOutcome:
        return run_evm_live_sell_blocking(
            blockchain_network=self._blockchain_network,
            token_symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            dex_id=dex_id,
            quantity=quantity,
            execution_price=execution_price,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        )
