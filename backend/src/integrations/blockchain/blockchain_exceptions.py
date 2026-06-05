from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.solana.solana_structures import SolanaRpcFailureReason


class BlockchainPriceUnavailableError(Exception):
    def __init__(self, message: str, blockchain_network: BlockchainNetwork) -> None:
        super().__init__(message)
        self.blockchain_network = blockchain_network


class BlockchainRpcUnavailableError(Exception):
    def __init__(
            self,
            message: str,
            blockchain_network: BlockchainNetwork,
            rpc_method: str,
            failure_reason: SolanaRpcFailureReason,
            rpc_url: str = "",
    ) -> None:
        super().__init__(message)
        self.blockchain_network = blockchain_network
        self.rpc_method = rpc_method
        self.failure_reason = failure_reason
        self.rpc_url = rpc_url


def is_transient_solana_rpc_failure(error: BlockchainRpcUnavailableError) -> bool:
    return error.failure_reason in {
        SolanaRpcFailureReason.RATE_LIMITED,
        SolanaRpcFailureReason.TIMEOUT,
        SolanaRpcFailureReason.NETWORK_ERROR,
        SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
    }


class BlockchainTradingNotSupportedError(Exception):
    def __init__(self, message: str, blockchain_network: BlockchainNetwork) -> None:
        super().__init__(message)
        self.blockchain_network = blockchain_network


class BlockchainExecutionRouteBuildError(Exception):
    def __init__(
            self,
            message: str,
            blockchain_network: BlockchainNetwork,
            is_transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.blockchain_network = blockchain_network
        self.is_transient = is_transient
