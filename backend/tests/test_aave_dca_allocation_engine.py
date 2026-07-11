from __future__ import annotations

from src.core.aavedca.aave_dca_allocation_engine import AaveDcaAllocationEngine
from src.core.aavedca.aave_dca_structures import AaveDcaAllocationDecision


def test_average_price_protection_halt_when_market_price_above_pru() -> None:
    allocation_verdict = AaveDcaAllocationEngine.calculate_dynamic_allocation(
        nominal_investment_amount=0.69,
        current_dry_powder_reserve=5.87,
        current_market_price=64200.0,
        current_macro_ema=64000.0,
        current_average_purchase_price=64082.0,
        price_elasticity_aggressiveness=1.0,
    )

    assert allocation_verdict.spend_amount == 0.0
    assert allocation_verdict.dry_powder_delta == 0.69
    assert allocation_verdict.allocation_decision == AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT
    assert allocation_verdict.allocation_multiplier == 1.0


def test_aggressive_dip_draws_partial_dry_powder_when_price_below_ema() -> None:
    allocation_verdict = AaveDcaAllocationEngine.calculate_dynamic_allocation(
        nominal_investment_amount=0.69,
        current_dry_powder_reserve=5.87,
        current_market_price=60000.0,
        current_macro_ema=64000.0,
        current_average_purchase_price=62000.0,
        price_elasticity_aggressiveness=1.0,
    )

    assert allocation_verdict.allocation_decision == AaveDcaAllocationDecision.AGGRESSIVE_DIP_ACCUMULATION_SCALED
    assert allocation_verdict.spend_amount > 0.69
    assert allocation_verdict.dry_powder_delta < 0.0


def test_last_cycle_still_respects_pru_protection() -> None:
    allocation_verdict = AaveDcaAllocationEngine.calculate_dynamic_allocation(
        nominal_investment_amount=0.69,
        current_dry_powder_reserve=5.87,
        current_market_price=64200.0,
        current_macro_ema=64000.0,
        current_average_purchase_price=64082.0,
        price_elasticity_aggressiveness=1.0,
    )

    assert allocation_verdict.spend_amount == 0.0
    assert allocation_verdict.allocation_decision == AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT
