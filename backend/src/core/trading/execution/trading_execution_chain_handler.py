from __future__ import annotations

from typing import Protocol

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.execution.trading_execution_structures import TradingLiveSellExecutionOutcome
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute


class TradingExecutionChainHandler(Protocol):
    def blockchain_network(self) -> BlockchainNetwork:
        ...

    def build_buy_route(self, candidate: TradingCandidate, order_notional_usd: float) -> BlockchainExecutionRoute:
        ...

    def build_sell_route(self, token_mint: str, token_quantity: float, token_decimals: int) -> BlockchainExecutionRoute:
        ...

    def resolve_sell_token_decimals(self, token_address: str) -> int:
        ...

    def cap_sell_quantity_to_wallet_balance(
            self,
            token_address: str,
            sell_quantity: float,
            token_decimals: int,
    ) -> float:
        ...

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
        ...

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
        ...
