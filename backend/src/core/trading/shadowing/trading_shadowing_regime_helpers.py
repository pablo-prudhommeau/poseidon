from __future__ import annotations

from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingPhase


def derive_trading_shadowing_phase(
        is_shadowing_enabled: bool,
        shadowing_ready: bool,
        shadow_gate_ready: bool,
        cortex_training_ready: bool,
        edge_gate_enabled: bool,
        toxic_metrics_gate_enabled: bool,
        cortex_gate_enabled: bool,
        shadowing_snapshot_ready: bool,
) -> TradingShadowingPhase:
    if not is_shadowing_enabled:
        return TradingShadowingPhase.DISABLED

    shadow_gate_enabled = edge_gate_enabled or toxic_metrics_gate_enabled
    if not shadow_gate_enabled and not cortex_gate_enabled:
        return TradingShadowingPhase.TRADABLE

    shadow_gate_requirement_satisfied = shadow_gate_ready or not shadow_gate_enabled
    trading_unblocked = (
            shadowing_ready
            and shadow_gate_requirement_satisfied
            and (cortex_training_ready or not cortex_gate_enabled)
    )
    if trading_unblocked and shadowing_snapshot_ready:
        return TradingShadowingPhase.TRADABLE
    if trading_unblocked:
        return TradingShadowingPhase.SYNCING

    cortexing_unlocked = shadowing_ready and shadow_gate_ready
    if cortex_gate_enabled and cortexing_unlocked:
        return TradingShadowingPhase.CORTEXING

    return TradingShadowingPhase.SHADOWING
