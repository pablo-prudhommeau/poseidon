from __future__ import annotations

from typing import Optional

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.execution.solana.trading_execution_solana_service import (
    build_solana_buy_route,
    build_solana_sell_route,
    cap_solana_sell_quantity_to_wallet_balance,
    resolve_solana_sell_token_decimals,
    run_solana_live_buy_blocking,
    run_solana_live_sell_blocking,
)
from src.core.trading.trading_structures import TradingCandidate
from src.integrations.blockchain.blockchain_live_executor import BlockchainExecutionResult
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute


class TradingExecutionSolanaHandler:
    def blockchain_network(self) -> BlockchainNetwork:
        return BlockchainNetwork.SOLANA

    def build_buy_route(self, candidate: TradingCandidate, order_notional_usd: float) -> Optional[BlockchainExecutionRoute]:
        return build_solana_buy_route(candidate, order_notional_usd)

    def build_sell_route(self, token_mint: str, token_quantity: float, token_decimals: int) -> Optional[BlockchainExecutionRoute]:
        return build_solana_sell_route(token_mint, token_quantity, token_decimals)

    def resolve_sell_token_decimals(self, token_address: str) -> Optional[int]:
        return resolve_solana_sell_token_decimals(token_address)

    def cap_sell_quantity_to_wallet_balance(
            self,
            token_address: str,
            sell_quantity: float,
            token_decimals: int,
    ) -> float:
        return cap_solana_sell_quantity_to_wallet_balance(token_address, sell_quantity, token_decimals)

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
        return run_solana_live_buy_blocking(
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
    ) -> Optional[BlockchainExecutionResult]:
        return run_solana_live_sell_blocking(
            token_symbol=token_symbol,
            token_address=token_address,
            pair_address=pair_address,
            dex_id=dex_id,
            quantity=quantity,
            execution_price=execution_price,
            execution_route=execution_route,
            origin_evaluation_id=origin_evaluation_id,
        )
