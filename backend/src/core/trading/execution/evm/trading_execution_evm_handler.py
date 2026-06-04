from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.trading_structures import TradingCandidate
from src.core.trading.execution.trading_execution_structures import TradingLiveSellExecutionOutcome
from src.integrations.blockchain.blockchain_exceptions import BlockchainTradingNotSupportedError
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute


class TradingExecutionEvmHandler:
    def __init__(self, blockchain_network: BlockchainNetwork) -> None:
        self._blockchain_network = blockchain_network

    def blockchain_network(self) -> BlockchainNetwork:
        return self._blockchain_network

    def build_buy_route(self, candidate: TradingCandidate, order_notional_usd: float) -> BlockchainExecutionRoute:
        raise BlockchainTradingNotSupportedError(
            f"Live buy route is not supported on {self._blockchain_network.value}",
            blockchain_network=self._blockchain_network,
        )

    def build_sell_route(self, token_mint: str, token_quantity: float, token_decimals: int) -> BlockchainExecutionRoute:
        raise BlockchainTradingNotSupportedError(
            f"Live sell route is not supported on {self._blockchain_network.value}",
            blockchain_network=self._blockchain_network,
        )

    def resolve_sell_token_decimals(self, token_address: str) -> int:
        raise BlockchainTradingNotSupportedError(
            f"Live sell token decimals are not supported on {self._blockchain_network.value}",
            blockchain_network=self._blockchain_network,
        )

    def cap_sell_quantity_to_wallet_balance(
            self,
            token_address: str,
            sell_quantity: float,
            token_decimals: int,
    ) -> float:
        return sell_quantity

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
        raise BlockchainTradingNotSupportedError(
            f"Live buy execution is not supported on {self._blockchain_network.value}",
            blockchain_network=self._blockchain_network,
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
        raise BlockchainTradingNotSupportedError(
            f"Live sell execution is not supported on {self._blockchain_network.value}",
            blockchain_network=self._blockchain_network,
        )
