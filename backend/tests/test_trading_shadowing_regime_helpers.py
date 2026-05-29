from __future__ import annotations

from src.core.trading.shadowing.trading_shadowing_regime_helpers import derive_trading_shadowing_phase
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingPhase


def _derive(**overrides):
    defaults = {
        "shadowing_ready": True,
        "shadow_gate_ready": True,
        "cortex_training_ready": True,
        "edge_gate_enabled": False,
        "toxic_metrics_gate_enabled": False,
        "cortex_gate_enabled": False,
        "fundamentals_gate_enabled": False,
        "shadowing_snapshot_ready": True,
        "edge_gate_satisfied": True,
    }
    defaults.update(overrides)
    return derive_trading_shadowing_phase(**defaults)


def test_disabled_when_all_trading_gates_off() -> None:
    phase = _derive()
    assert phase == TradingShadowingPhase.DISABLED


def test_tradable_when_only_cortex_gate_enabled_and_warmup_complete() -> None:
    phase = _derive(cortex_gate_enabled=True)
    assert phase == TradingShadowingPhase.TRADABLE


def test_shadowing_when_cortex_gate_enabled_but_gate_ready_threshold_not_reached() -> None:
    phase = _derive(
        cortex_gate_enabled=True,
        shadow_gate_ready=False,
    )
    assert phase == TradingShadowingPhase.SHADOWING


def test_cortexing_when_gate_ready_reached_but_cortex_training_threshold_not_reached() -> None:
    phase = _derive(
        cortex_gate_enabled=True,
        shadow_gate_ready=True,
        cortex_training_ready=False,
    )
    assert phase == TradingShadowingPhase.CORTEXING


def test_bear_when_edge_gate_enabled_but_not_satisfied() -> None:
    phase = _derive(
        edge_gate_enabled=True,
        edge_gate_satisfied=False,
    )
    assert phase == TradingShadowingPhase.BEAR
