from __future__ import annotations

from typing import Optional

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.trading_structures import TradingCandidate
from src.core.trading.execution.trading_execution_structures import TradingLiveSellExecutionOutcome
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_TRADING_NOT_SUPPORTED_REASON = "evm_trading_not_supported"


class TradingExecutionEvmHandler:
    def __init__(self, blockchain_network: BlockchainNetwork) -> None:
        self._blockchain_network = blockchain_network

    def blockchain_network(self) -> BlockchainNetwork:
        return self._blockchain_network

    def build_buy_route(self, candidate: TradingCandidate, order_notional_usd: float) -> Optional[BlockchainExecutionRoute]:
        logger.warning(
            "[TRADING][EXECUTION][EVM][ROUTE] Buy route denied — blockchain_network=%s token=%s reason=%s",
            self._blockchain_network.value,
            candidate.token.symbol,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return None

    def build_sell_route(self, token_mint: str, token_quantity: float, token_decimals: int) -> Optional[BlockchainExecutionRoute]:
        logger.warning(
            "[TRADING][EXECUTION][EVM][ROUTE] Sell route denied — blockchain_network=%s reason=%s",
            self._blockchain_network.value,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return None

    def resolve_sell_token_decimals(self, token_address: str) -> Optional[int]:
        logger.warning(
            "[TRADING][EXECUTION][EVM][POSITION] Sell token decimals unavailable — blockchain_network=%s reason=%s",
            self._blockchain_network.value,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return None

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
        logger.warning(
            "[TRADING][EXECUTION][EVM][SWAP] Live buy blocked — blockchain_network=%s token=%s reason=%s",
            self._blockchain_network.value,
            token.symbol,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return False

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
        logger.warning(
            "[TRADING][EXECUTION][EVM][SWAP] Live sell blocked — blockchain_network=%s token=%s reason=%s",
            self._blockchain_network.value,
            token_symbol,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return TradingLiveSellExecutionOutcome(execution_result=None, failure_reason=None)
