from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingLifiRoute
from src.integrations.lifi.lifi_client import generate_native_to_token_route, resolve_lifi_chain_identifier
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


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


def build_lifi_route_for_live_execution(candidate: TradingCandidate, order_notional_usd: float) -> Optional[TradingLifiRoute]:
    if settings.PAPER_MODE:
        return None

    token_information = candidate.dexscreener_token_information
    chain_key = (token_information.chain_id or "").strip().lower()

    if chain_key == "solana":
        return _build_solana_route(candidate, order_notional_usd)

    return _build_evm_route(candidate, order_notional_usd, chain_key)


def _build_solana_route(candidate: TradingCandidate, order_notional_usd: float) -> Optional[TradingLifiRoute]:
    token_information = candidate.dexscreener_token_information
    token_mint = (token_information.base_token.address or "").strip()
    if not token_mint:
        logger.debug("[TRADING][ORDER][ROUTE] Missing SPL token mint for %s on Solana", token_information.base_token.symbol)
        return None

    from_amount_lamports = _compute_from_amount_lamports(order_notional_usd, candidate)
    if from_amount_lamports is None:
        logger.debug("[TRADING][ORDER][ROUTE] Cannot compute lamports for %s on Solana", token_information.base_token.symbol)
        return None

    try:
        from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
        sol_signer = build_default_solana_signer()
        from_address = sol_signer.address
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] Solana signer unavailable: %s", exception)
        return None

    try:
        route = generate_native_to_token_route(
            chain_identifier="solana",
            source_address=from_address,
            destination_token_address=token_mint,
            source_amount_wei=from_amount_lamports,
            slippage_tolerance=settings.TRADING_SLIPPAGE_TOLERANCE,
        )
        return route
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] LI.FI route build failed for %s on solana: %s", token_information.base_token.symbol, exception)
        return None


def _build_evm_route(candidate: TradingCandidate, order_notional_usd: float, chain_key: str) -> Optional[TradingLifiRoute]:
    token_information = candidate.dexscreener_token_information
    chain_id = resolve_lifi_chain_identifier(chain_key)
    if chain_id is None:
        logger.debug("[TRADING][ORDER][ROUTE] Unsupported chain '%s'", chain_key or "?")
        return None

    to_token_address = (token_information.base_token.address or "").strip()
    if not to_token_address:
        logger.debug("[TRADING][ORDER][ROUTE] Missing ERC-20 token address for %s", token_information.base_token.symbol)
        return None

    from_amount_wei = _compute_from_amount_wei(order_notional_usd, candidate)
    if from_amount_wei is None:
        logger.debug("[TRADING][ORDER][ROUTE] Cannot compute wei for %s", token_information.base_token.symbol)
        return None

    try:
        from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer
        evm_signer = build_default_evm_signer()
        evm_address = evm_signer.wallet_address
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] EVM signer unavailable: %s", exception)
        return None

    try:
        route = generate_native_to_token_route(
            chain_identifier=chain_key,
            source_address=evm_address,
            destination_token_address=to_token_address,
            source_amount_wei=from_amount_wei,
            slippage_tolerance=settings.TRADING_SLIPPAGE_TOLERANCE,
        )
        return route
    except Exception as exception:
        logger.exception("[TRADING][ORDER][ROUTE] LI.FI route build failed for %s on %s: %s", token_information.base_token.symbol, chain_key, exception)
        return None
