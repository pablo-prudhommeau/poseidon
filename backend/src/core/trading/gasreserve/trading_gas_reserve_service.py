from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.evm.trading_gas_reserve_evm_handler import TradingGasReserveEvmHandler
from src.core.trading.gasreserve.evm.trading_gas_reserve_evm_service import (
    is_evm_gas_reserve_sufficient_for_buy_on_blockchain,
    resolve_evm_onchain_wallet_context,
)
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_handler import TradingGasReserveSolanaHandler
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service import (
    is_solana_gas_reserve_sufficient_for_buy,
)
from src.core.trading.gasreserve.trading_gas_reserve_chain_handler import TradingGasReserveChainHandler
from src.core.trading.gasreserve.trading_gas_reserve_structures import (
    GasRefillLockedStablecoinSnapshot,
    TradingGasReserveChainHandlerRegistry,
    WalletAuxiliaryAssetsSnapshot,
)
from src.core.trading.trading_chain_capability_service import (
    is_trading_evm_blockchain_network,
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_structures import TradingConfigurationError
from src.core.utils.math_utils import decimal_from_primitive, quantize_2dp
from src.integrations.blockchain.solana.solana_onchain_wallet_context_service import (
    resolve_solana_onchain_wallet_context_for_live_trading,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def resolve_gas_reserve_chain_handlers() -> list[TradingGasReserveChainHandler]:
    handlers: list[TradingGasReserveChainHandler] = []
    for blockchain_network in resolve_trading_allowed_blockchain_networks():
        if blockchain_network == BlockchainNetwork.SOLANA:
            solana_wallet_context = resolve_solana_onchain_wallet_context_for_live_trading()
            handlers.append(TradingGasReserveSolanaHandler(wallet_context=solana_wallet_context))
        elif is_trading_evm_blockchain_network(blockchain_network):
            try:
                evm_wallet_context = resolve_evm_onchain_wallet_context(blockchain_network)
            except Exception:
                logger.exception(
                    "[TRADING][GASRESERVE][SERVICE] Failed to resolve EVM wallet context — blockchain_network=%s",
                    blockchain_network.value,
                )
                raise
            handlers.append(
                TradingGasReserveEvmHandler(
                    blockchain_network=blockchain_network,
                    wallet_context=evm_wallet_context,
                ),
            )
    return handlers


def is_gas_reserve_sufficient_for_buy(blockchain_network: BlockchainNetwork) -> bool:
    if settings.TRADING_PAPER_MODE:
        return True

    if blockchain_network == BlockchainNetwork.SOLANA:
        return is_solana_gas_reserve_sufficient_for_buy()

    if is_trading_evm_blockchain_network(blockchain_network):
        return is_evm_gas_reserve_sufficient_for_buy_on_blockchain(blockchain_network)

    raise TradingConfigurationError(
        f"No gas reserve buy guard registered for configured blockchain '{blockchain_network.value}'",
    )


def _is_any_live_gas_reserve_chain_enabled() -> bool:
    return len(resolve_trading_allowed_blockchain_networks()) > 0


def resolve_gas_reserve_chain_handlers_for_liquidity_payload() -> TradingGasReserveChainHandlerRegistry:
    return TradingGasReserveChainHandlerRegistry(
        handlers=resolve_gas_reserve_chain_handlers(),
    )


def resolve_gas_refill_locked_stablecoin_snapshots() -> list[GasRefillLockedStablecoinSnapshot]:
    if settings.TRADING_PAPER_MODE or not _is_any_live_gas_reserve_chain_enabled():
        return []

    chain_handlers = resolve_gas_reserve_chain_handlers()
    snapshots: list[GasRefillLockedStablecoinSnapshot] = []
    for chain_handler in chain_handlers:
        snapshots.append(chain_handler.compute_gas_refill_locked_stablecoin_snapshot())
    return snapshots


def resolve_wallet_auxiliary_assets_snapshots() -> list[WalletAuxiliaryAssetsSnapshot]:
    if settings.TRADING_PAPER_MODE or not _is_any_live_gas_reserve_chain_enabled():
        return []

    chain_handlers = resolve_gas_reserve_chain_handlers()
    snapshots: list[WalletAuxiliaryAssetsSnapshot] = []
    for chain_handler in chain_handlers:
        snapshots.append(chain_handler.compute_wallet_auxiliary_assets_snapshot())
    return snapshots


def compute_total_gas_refill_locked_stablecoin_usd() -> float:
    total_locked: float = 0.0
    for locked_snapshot in resolve_gas_refill_locked_stablecoin_snapshots():
        total_locked += locked_snapshot.gas_refill_locked_stablecoin_usd
    return float(quantize_2dp(decimal_from_primitive(total_locked)))


def compute_total_wallet_auxiliary_assets_usd() -> float:
    total_wallet_auxiliary: float = 0.0
    for wallet_auxiliary_snapshot in resolve_wallet_auxiliary_assets_snapshots():
        total_wallet_auxiliary += wallet_auxiliary_snapshot.total_wallet_auxiliary_assets_usd
    return float(quantize_2dp(decimal_from_primitive(total_wallet_auxiliary)))


def compute_net_deployable_cash_usd(total_stablecoin_usd: float) -> float:
    total_locked_usd = compute_total_gas_refill_locked_stablecoin_usd()
    net_deployable_cash_usd = max(0.0, total_stablecoin_usd - total_locked_usd)
    logger.debug(
        "[TRADING][GASRESERVE][SERVICE] Computed net deployable cash — total_stablecoin_usd=%.2f "
        "total_locked_usd=%.2f net_deployable_cash_usd=%.2f",
        total_stablecoin_usd,
        total_locked_usd,
        net_deployable_cash_usd,
    )
    return float(quantize_2dp(decimal_from_primitive(net_deployable_cash_usd)))
