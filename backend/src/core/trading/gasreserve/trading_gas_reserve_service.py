from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_handler import TradingGasReserveSolanaHandler
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service import (
    is_solana_gas_reserve_sufficient_for_buy,
)
from src.core.trading.gasreserve.trading_gas_reserve_chain_handler import TradingGasReserveChainHandler
from src.core.trading.gasreserve.trading_gas_reserve_structures import (
    GasRefillLockedStablecoinSnapshot,
    WalletAuxiliaryAssetsSnapshot,
)
from src.core.trading.trading_chain_capability_service import (
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.trading_structures import TradingConfigurationError
from src.core.utils.math_utils import decimal_from_primitive, quantize_2dp
from src.integrations.blockchain.solana.solana_onchain_wallet_context_service import (
    resolve_required_solana_onchain_wallet_context_for_live_portfolio,
    resolve_solana_onchain_wallet_context_for_live_trading,
)
from src.integrations.blockchain.solana.solana_structures import SolanaOnchainWalletContext
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def resolve_gas_reserve_chain_handlers(
        solana_wallet_context: SolanaOnchainWalletContext,
) -> list[TradingGasReserveChainHandler]:
    handlers: list[TradingGasReserveChainHandler] = []
    for blockchain_network in resolve_trading_allowed_blockchain_networks():
        if blockchain_network == BlockchainNetwork.SOLANA:
            handlers.append(TradingGasReserveSolanaHandler(wallet_context=solana_wallet_context))
    return handlers


def is_gas_reserve_sufficient_for_buy(blockchain_network: BlockchainNetwork) -> bool:
    if settings.TRADING_PAPER_MODE:
        return True

    if blockchain_network == BlockchainNetwork.SOLANA:
        return is_solana_gas_reserve_sufficient_for_buy()

    raise TradingConfigurationError(
        f"No gas reserve buy guard registered for configured blockchain '{blockchain_network.value}'",
    )


def _is_solana_gas_reserve_chain_enabled() -> bool:
    for blockchain_network in resolve_trading_allowed_blockchain_networks():
        if blockchain_network == BlockchainNetwork.SOLANA:
            return True
    return False


def _resolve_solana_wallet_context_for_live_gas_reserve() -> SolanaOnchainWalletContext:
    wallet_context = resolve_solana_onchain_wallet_context_for_live_trading()
    logger.debug(
        "[TRADING][GASRESERVE][SERVICE] Resolved Solana wallet context for live gas reserve — "
        "blockchain_network=%s native_sol=%.6f stablecoin_balance=%.2f",
        BlockchainNetwork.SOLANA.value,
        wallet_context.native_token_balance_raw,
        wallet_context.stablecoin_balance_raw,
    )
    return wallet_context


def resolve_gas_reserve_chain_handlers_for_liquidity_payload() -> dict[BlockchainNetwork, TradingGasReserveChainHandler]:
    solana_wallet_context = resolve_required_solana_onchain_wallet_context_for_live_portfolio()
    chain_handlers = resolve_gas_reserve_chain_handlers(
        solana_wallet_context=solana_wallet_context,
    )
    chain_handler_by_blockchain_network: dict[BlockchainNetwork, TradingGasReserveChainHandler] = {}
    for chain_handler in chain_handlers:
        chain_handler_by_blockchain_network[chain_handler.blockchain_network()] = chain_handler
    return chain_handler_by_blockchain_network


def resolve_gas_refill_locked_stablecoin_snapshots() -> list[GasRefillLockedStablecoinSnapshot]:
    if settings.TRADING_PAPER_MODE or not _is_solana_gas_reserve_chain_enabled():
        return []

    solana_wallet_context = _resolve_solana_wallet_context_for_live_gas_reserve()
    chain_handlers = resolve_gas_reserve_chain_handlers(
        solana_wallet_context=solana_wallet_context,
    )
    snapshots: list[GasRefillLockedStablecoinSnapshot] = []
    for chain_handler in chain_handlers:
        snapshots.append(chain_handler.compute_gas_refill_locked_stablecoin_snapshot())
    return snapshots


def resolve_wallet_auxiliary_assets_snapshots() -> list[WalletAuxiliaryAssetsSnapshot]:
    if settings.TRADING_PAPER_MODE or not _is_solana_gas_reserve_chain_enabled():
        return []

    solana_wallet_context = _resolve_solana_wallet_context_for_live_gas_reserve()
    chain_handlers = resolve_gas_reserve_chain_handlers(
        solana_wallet_context=solana_wallet_context,
    )
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
