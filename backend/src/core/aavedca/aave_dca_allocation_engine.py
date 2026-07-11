from __future__ import annotations

from src.core.aavedca.aave_dca_structures import AllocationResult, AaveDcaAllocationDecision
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveDcaAllocationEngine:

    @staticmethod
    def calculate_dynamic_allocation(
            nominal_investment_amount: float,
            current_dry_powder_reserve: float,
            current_market_price: float,
            current_macro_ema: float,
            current_average_purchase_price: float,
            price_elasticity_aggressiveness: float
    ) -> AllocationResult:
        logger.debug(
            "[AAVEDCA][ALLOCATION][CHECK] Nominal: %s | DryPowder: %s | Price: %s | PRU: %s",
            nominal_investment_amount,
            current_dry_powder_reserve,
            current_market_price,
            current_average_purchase_price
        )

        if current_average_purchase_price > 0 and current_market_price > current_average_purchase_price:
            logger.debug("[AAVEDCA][ALLOCATION][SKIP] Kill-switch active: market price is above average purchase price")
            return AllocationResult(
                spend_amount=0.0,
                dry_powder_delta=nominal_investment_amount,
                allocation_decision=AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT,
                allocation_multiplier=1.0
            )

        investment_multiplier = 1.0
        if current_average_purchase_price > 0 and current_market_price <= current_average_purchase_price:
            distance_from_pru_percent = (current_average_purchase_price - current_market_price) / current_average_purchase_price
            investment_multiplier = 1.0 + (distance_from_pru_percent * price_elasticity_aggressiveness)
            logger.debug("[AAVEDCA][ALLOCATION][SCALING] Elasticity multiplier calculated: %s", investment_multiplier)

        if current_macro_ema > 0 and current_market_price > current_macro_ema:
            base_allocation_amount = nominal_investment_amount * 0.5
            target_spend_amount = base_allocation_amount * investment_multiplier
            allocation_decision = AaveDcaAllocationDecision.CONSERVATIVE_RETENTION_SCALED
        elif current_macro_ema > 0 and current_market_price <= current_macro_ema:
            base_allocation_amount = nominal_investment_amount + (current_dry_powder_reserve * 0.5)
            target_spend_amount = base_allocation_amount * investment_multiplier
            allocation_decision = AaveDcaAllocationDecision.AGGRESSIVE_DIP_ACCUMULATION_SCALED
        else:
            target_spend_amount = nominal_investment_amount * investment_multiplier
            allocation_decision = AaveDcaAllocationDecision.FALLBACK_NOMINAL_STRATEGY

        max_available_liquidity = nominal_investment_amount + current_dry_powder_reserve
        actual_spend_amount = min(target_spend_amount, max_available_liquidity)
        dry_powder_delta = nominal_investment_amount - actual_spend_amount

        logger.debug(
            "[AAVEDCA][ALLOCATION][RESULT] Decision: %s | Spend: %s | Multiplier: %s",
            allocation_decision.value,
            actual_spend_amount,
            investment_multiplier
        )

        return AllocationResult(
            spend_amount=actual_spend_amount,
            dry_powder_delta=dry_powder_delta,
            allocation_decision=allocation_decision,
            allocation_multiplier=investment_multiplier
        )
