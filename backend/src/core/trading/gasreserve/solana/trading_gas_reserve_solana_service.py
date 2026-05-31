from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_helpers import (
    BUY_GUARD_RESERVE_CYCLE_COUNT,
    build_solana_gas_reserve_cost_snapshot,
    compute_reserve_lamports,
)
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
from src.integrations.blockchain.solana.solana_rpc_client import (
    fetch_solana_native_balance_lamports,
    format_lamports_as_sol_text,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def is_solana_gas_reserve_sufficient_for_buy() -> bool:
    cost_snapshot = build_solana_gas_reserve_cost_snapshot()
    required_native_reserve_raw = compute_reserve_lamports(
        cycle_cost_lamports=cost_snapshot.cycle_cost_lamports,
        cycle_count=BUY_GUARD_RESERVE_CYCLE_COUNT,
    )

    native_balance_raw = _fetch_solana_native_balance_raw()
    if native_balance_raw is None:
        logger.warning(
            "[TRADING][GASRESERVE][SOLANA][GUARD] Buy blocked — native balance unavailable — "
            "blockchain_network=%s reason=native_balance_unavailable",
            BlockchainNetwork.SOLANA.value,
        )
        return False

    is_sufficient = native_balance_raw >= required_native_reserve_raw
    if not is_sufficient:
        logger.info(
            "[TRADING][GASRESERVE][SOLANA][GUARD] Buy blocked — native balance below gas reserve — "
            "blockchain_network=%s native_balance=%s required_reserve=%s cycle_cost=%s "
            "reason=INSUFFICIENT_GAS_RESERVE",
            BlockchainNetwork.SOLANA.value,
            format_lamports_as_sol_text(native_balance_raw),
            format_lamports_as_sol_text(required_native_reserve_raw),
            format_lamports_as_sol_text(cost_snapshot.cycle_cost_lamports),
        )
    return is_sufficient


def _fetch_solana_native_balance_raw() -> int | None:
    blockchain_network = BlockchainNetwork.SOLANA
    rpc_url = resolve_rpc_url_for_chain(blockchain_network)
    try:
        wallet_address = build_default_solana_signer().address
    except Exception:
        logger.exception(
            "[TRADING][GASRESERVE][SOLANA][GUARD] Signer unavailable — "
            "blockchain_network=%s reason=signer_unavailable",
            blockchain_network.value,
        )
        return None

    return fetch_solana_native_balance_lamports(rpc_url, wallet_address)
