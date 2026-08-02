from __future__ import annotations

from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingPhase


def derive_trading_shadowing_phase(
        shadowing_ready: bool,
        shadow_gate_ready: bool,
        cortex_training_ready: bool,
        edge_gate_enabled: bool,
        toxic_metrics_gate_enabled: bool,
        cortex_gate_enabled: bool,
        fundamentals_gate_enabled: bool,
        liquidity_structure_gate_enabled: bool,
        shadowing_snapshot_ready: bool,
        edge_gate_satisfied: bool,
) -> TradingShadowingPhase:
    any_gate_enabled = (
            edge_gate_enabled
            or toxic_metrics_gate_enabled
            or cortex_gate_enabled
            or fundamentals_gate_enabled
            or liquidity_structure_gate_enabled
    )
    if not any_gate_enabled:
        return TradingShadowingPhase.DISABLED

    shadow_gate_enabled = edge_gate_enabled or toxic_metrics_gate_enabled
    if not shadow_gate_enabled and not cortex_gate_enabled:
        return TradingShadowingPhase.TRADABLE

    trading_unblocked = (
            shadowing_ready
            and shadow_gate_ready
            and (cortex_training_ready or not cortex_gate_enabled)
    )
    if trading_unblocked and shadowing_snapshot_ready:
        if edge_gate_enabled and not edge_gate_satisfied:
            return TradingShadowingPhase.BEAR
        return TradingShadowingPhase.TRADABLE
    if trading_unblocked:
        return TradingShadowingPhase.SYNCING

    if cortex_gate_enabled and shadow_gate_ready:
        return TradingShadowingPhase.CORTEXING

    return TradingShadowingPhase.SHADOWING
