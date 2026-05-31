from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_TRADING_NOT_SUPPORTED_REASON = "evm_trading_not_supported"


class TradingGasReserveEvmHandler:
    def __init__(self, blockchain_network: BlockchainNetwork) -> None:
        self._blockchain_network = blockchain_network

    def blockchain_network(self) -> BlockchainNetwork:
        return self._blockchain_network

    def is_gas_reserve_sufficient_for_buy(self) -> bool:
        logger.warning(
            "[TRADING][GASRESERVE][EVM][GUARD] Buy blocked — gas reserve guard not implemented — "
            "blockchain_network=%s reason=%s",
            self._blockchain_network.value,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return False
