from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from src.configuration.config import settings
from src.core.aavedca.aave_dca_structures import AaveDcaAllocationDecision, AaveDcaOrderStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_structures import AaveEvmTransactionConfirmationFailureKind


def convert_token_amount_to_base_units(token_amount: float, token_decimals: int) -> int:
    decimal_amount: Decimal = Decimal(str(token_amount))
    scale_factor: Decimal = Decimal(10) ** token_decimals
    base_units: Decimal = decimal_amount * scale_factor
    return int(base_units)


def compute_implied_swap_price_usd(
        source_amount_base_units: int,
        target_amount_base_units: int,
        source_asset_decimals: int,
        target_asset_decimals: int,
) -> float:
    source_amount_decimal: Decimal = Decimal(source_amount_base_units) / Decimal(10) ** source_asset_decimals
    target_amount_decimal: Decimal = Decimal(target_amount_base_units) / Decimal(10) ** target_asset_decimals
    if target_amount_decimal <= Decimal(0):
        return 0.0
    return float(source_amount_decimal / target_amount_decimal)


def compute_price_deviation_percent(reference_price_usd: float, implied_price_usd: float) -> float:
    if reference_price_usd <= 0 or implied_price_usd <= 0:
        return 100.0
    return abs(implied_price_usd - reference_price_usd) / reference_price_usd * 100.0


def compute_pipeline_backoff_delay_seconds(attempt_count: int) -> int:
    exponential_delay_seconds: int = settings.AAVE_DCA_PIPELINE_BASE_BACKOFF_SECONDS * (2 ** max(attempt_count - 1, 0))
    return min(exponential_delay_seconds, settings.AAVE_DCA_PIPELINE_MAX_BACKOFF_SECONDS)


def compute_pipeline_next_attempt_at(attempt_count: int) -> datetime:
    delay_seconds: int = compute_pipeline_backoff_delay_seconds(attempt_count)
    return get_current_local_datetime() + timedelta(seconds=delay_seconds)


def resolve_pipeline_step_descriptor(order_status: AaveDcaOrderStatus) -> Optional[tuple[int, str]]:
    if order_status == AaveDcaOrderStatus.AWAITING_WITHDRAW:
        return 1, "Withdraw Aave"
    if order_status == AaveDcaOrderStatus.AWAITING_SWAP:
        return 2, "Swap LI.FI"
    if order_status == AaveDcaOrderStatus.AWAITING_SUPPLY:
        return 3, "Supply Aave"
    return None


def resolve_allocation_decision_display_title(allocation_decision: AaveDcaAllocationDecision) -> str:
    if allocation_decision == AaveDcaAllocationDecision.AGGRESSIVE_DIP_ACCUMULATION_SCALED:
        return "Accumulation Agressive 🚀"
    if allocation_decision == AaveDcaAllocationDecision.CONSERVATIVE_RETENTION_SCALED:
        return "Accumulation Prudente 🛡️"
    if allocation_decision == AaveDcaAllocationDecision.FALLBACK_NOMINAL_STRATEGY:
        return "Stratégie Nominale ⚖️"
    if allocation_decision == AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT:
        return "Protection PRU [Halt] 🛑"
    return "Exécution Stratégique"


def format_allocation_decision_label(
        allocation_decision: AaveDcaAllocationDecision,
        allocation_multiplier: Optional[float],
) -> str:
    if allocation_multiplier is not None and allocation_multiplier != 1.0:
        return f"{allocation_decision.value} (×{allocation_multiplier:.2f})"
    return allocation_decision.value


def build_aave_dca_pipeline_step_failure_message(
        pipeline_step_label: str,
        onchain_revert_reason: Optional[str],
        confirmation_failure_kind: Optional[AaveEvmTransactionConfirmationFailureKind],
) -> str:
    if confirmation_failure_kind == AaveEvmTransactionConfirmationFailureKind.CONFIRMATION_TIMEOUT:
        return f"{pipeline_step_label} transaction confirmation timed out"
    if onchain_revert_reason is not None and onchain_revert_reason.strip():
        return f"{pipeline_step_label} transaction reverted on-chain: {onchain_revert_reason.strip()}"
    return f"{pipeline_step_label} transaction not confirmed"


def resolve_closest_market_timestamp(market_timestamps: list[int], target_timestamp: int) -> int:
    return min(market_timestamps, key=lambda current_timestamp: abs(current_timestamp - target_timestamp))
