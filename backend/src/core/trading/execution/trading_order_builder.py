from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_structures import TradingCandidate, TradingExecutionRoute, TradingSolanaRoute, TradingEvmRoute
from src.integrations.blockchain.blockchain_free_cash_service import _get_stablecoin_address_for_blockchain
from src.integrations.jupiter.jupiter_client import generate_jupiter_swap_transaction
from src.integrations.lifi.lifi_client import generate_token_to_token_route, resolve_lifi_chain_identifier
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def build_route_for_live_sell(
        token_mint: str,
        chain: BlockchainNetwork,
        token_quantity: float,
        token_decimals: int
) -> Optional[TradingExecutionRoute]:
    if settings.PAPER_MODE:
        return None

    if chain == BlockchainNetwork.SOLANA:
        return _build_solana_sell_route(token_mint, token_quantity, token_decimals)

    logger.warning(
        "[TRADING][ORDER][ROUTE] Live trading is restricted to Solana. Sell route denied for chain=%s",
        chain.value,
    )
    return None


def build_route_for_live_execution(candidate: TradingCandidate, order_notional_usd: float) -> Optional[TradingExecutionRoute]:
    if settings.PAPER_MODE:
        return None

    chain = candidate.token.chain
    if chain == BlockchainNetwork.SOLANA:
        return _build_solana_route(candidate, order_notional_usd)

    logger.warning(
        "[TRADING][ORDER][ROUTE] Live trading is restricted to Solana. Buy route denied for chain=%s token=%s",
        chain.value,
        candidate.token.symbol,
    )
    return None


def _build_solana_route(candidate: TradingCandidate, order_notional_usd: float) -> Optional[TradingExecutionRoute]:
    token_information = candidate.dexscreener_token_information
    token_mint = (token_information.base_token.address or "").strip()
    if not token_mint:
        logger.debug("[TRADING][ORDER][ROUTE] Missing SPL token mint for %s on Solana", token_information.base_token.symbol)
        return None

    stablecoin_address = _get_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    if not stablecoin_address:
        logger.debug("[TRADING][ORDER][ROUTE] Missing stablecoin address for Solana")
        return None

    from_amount_raw = _compute_from_amount_stablecoin_raw(order_notional_usd, BlockchainNetwork.SOLANA)
    if from_amount_raw is None:
        logger.debug("[TRADING][ORDER][ROUTE] Cannot compute stablecoin raw amount for %s on Solana", token_information.base_token.symbol)
        return None

    try:
        from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
        sol_signer = build_default_solana_signer()
        from_address = sol_signer.address
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] Solana signer unavailable: %s", exception)
        return None

    try:
        slippage_basis_points = int(settings.TRADING_SLIPPAGE_TOLERANCE * 10000)
        base64_transaction = generate_jupiter_swap_transaction(
            source_address=from_address,
            input_mint=stablecoin_address,
            output_mint=token_mint,
            amount_in_lamports=from_amount_raw,
            slippage_basis_points=slippage_basis_points
        )
        solana_route = TradingSolanaRoute(serialized_transaction_base64=base64_transaction)
        return TradingExecutionRoute(solana_route=solana_route)
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] Jupiter route build failed for %s on solana: %s", token_information.base_token.symbol, exception)
        return None


def _build_evm_route(candidate: TradingCandidate, order_notional_usd: float, chain: BlockchainNetwork) -> Optional[TradingExecutionRoute]:
    token_information = candidate.dexscreener_token_information
    chain_id = resolve_lifi_chain_identifier(chain)
    if chain_id is None:
        logger.debug("[TRADING][ORDER][ROUTE] Unsupported chain '%s'", chain.value)
        return None

    to_token_address = (token_information.base_token.address or "").strip()
    if not to_token_address:
        logger.debug("[TRADING][ORDER][ROUTE] Missing ERC-20 token address for %s", token_information.base_token.symbol)
        return None

    stablecoin_address = _get_stablecoin_address_for_blockchain(chain)
    if not stablecoin_address:
        logger.debug("[TRADING][ORDER][ROUTE] Missing stablecoin address for %s", chain.value)
        return None

    from_amount_raw = _compute_from_amount_stablecoin_raw(order_notional_usd, chain)
    if from_amount_raw is None:
        logger.debug("[TRADING][ORDER][ROUTE] Cannot compute stablecoin raw amount for %s on %s", token_information.base_token.symbol, chain.value)
        return None

    try:
        from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer
        evm_signer = build_default_evm_signer(chain=chain)
        evm_address = evm_signer.wallet_address
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] EVM signer unavailable: %s", exception)
        return None

    try:
        lifi_route = generate_token_to_token_route(
            chain=chain,
            source_address=evm_address,
            source_token_address=stablecoin_address,
            destination_token_address=to_token_address,
            source_amount_wei=from_amount_raw,
            slippage_tolerance=settings.TRADING_SLIPPAGE_TOLERANCE,
        )
        if lifi_route is None or lifi_route.transaction_request is None:
            return None

        evm_route = TradingEvmRoute(transaction_request=lifi_route.transaction_request)
        return TradingExecutionRoute(evm_route=evm_route)
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] LI.FI route build failed for %s on %s: %s", token_information.base_token.symbol, chain.value, exception)
        return None


def _build_solana_sell_route(token_mint: str, token_quantity: float, token_decimals: int) -> Optional[TradingExecutionRoute]:
    if not token_mint:
        return None

    amount_lamports = int(token_quantity * (10 ** token_decimals))
    if amount_lamports <= 0:
        return None

    stablecoin_address = _get_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    if not stablecoin_address:
        logger.debug("[TRADING][ORDER][ROUTE] Missing stablecoin address for Solana (sell)")
        return None

    try:
        from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
        sol_signer = build_default_solana_signer()
        from_address = sol_signer.address
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] Solana signer unavailable: %s", exception)
        return None

    try:
        slippage_basis_points = int(settings.TRADING_SLIPPAGE_TOLERANCE * 10000)
        base64_transaction = generate_jupiter_swap_transaction(
            source_address=from_address,
            input_mint=token_mint,
            output_mint=stablecoin_address,
            amount_in_lamports=amount_lamports,
            slippage_basis_points=slippage_basis_points
        )
        solana_route = TradingSolanaRoute(serialized_transaction_base64=base64_transaction)
        return TradingExecutionRoute(solana_route=solana_route)
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] Jupiter route build failed for %s on solana (sell): %s", token_mint, exception)
        return None


def _compute_from_amount_wei(order_notional_usd: float, candidate: TradingCandidate) -> Optional[int]:
    token_information = candidate.dexscreener_token_information
    try:
        price_usd = token_information.price_usd
        price_native = token_information.price_native
        if price_usd <= 0.0 or price_native <= 0.0:
            return None

        token_amount = order_notional_usd / price_usd
        native_amount = token_amount * price_native
        wei_amount = int(native_amount * (10 ** 18))
        return wei_amount if wei_amount > 0 else None
    except Exception:
        return None


def _compute_from_amount_lamports(order_notional_usd: float, candidate: TradingCandidate) -> Optional[int]:
    try:
        token_information = candidate.dexscreener_token_information
        price_usd = token_information.price_usd
        price_native = token_information.price_native
        if price_usd <= 0.0 or price_native <= 0.0:
            return None

        token_amount = order_notional_usd / price_usd
        native_amount = token_amount * price_native
        lamports = int(native_amount * (10 ** 9))
        return lamports if lamports > 0 else None
    except Exception:
        return None


def _compute_from_amount_stablecoin_raw(order_notional_usd: float, chain: BlockchainNetwork) -> Optional[int]:
    try:
        decimals = 18 if chain == BlockchainNetwork.BSC else 6
        amount_raw = int(order_notional_usd * (10 ** decimals))
        return amount_raw if amount_raw > 0 else None
    except Exception:
        return None
