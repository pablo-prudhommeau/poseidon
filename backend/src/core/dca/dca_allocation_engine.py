from __future__ import annotations

from src.core.structures.structures import AllocationResult
from src.logging.logger import get_logger

logger = get_logger(__name__)


class DcaAllocationEngine:

    @staticmethod
    def calculate_dynamic_allocation(
            nominal_investment_amount: float,
            current_dry_powder_reserve: float,
            current_market_price: float,
            current_macro_ema: float,
            current_average_purchase_price: float,
            is_last_execution_cycle: bool,
            price_elasticity_aggressiveness: float
    ) -> AllocationResult:
        logger.debug(
            "[DCA][ALLOCATION][CHECK] Nominal: %s | DryPowder: %s | Price: %s | PRU: %s",
            nominal_investment_amount,
            current_dry_powder_reserve,
            current_market_price,
            current_average_purchase_price
        )

        if is_last_execution_cycle:
            total_remaining_liquidity = nominal_investment_amount + current_dry_powder_reserve
            logger.info("[DCA][ALLOCATION][FINAL] Final execution cycle triggered: deploying all remaining liquidity")
            return AllocationResult(
                spend_amount=total_remaining_liquidity,
                dry_powder_delta=-current_dry_powder_reserve,
                action_description="FINAL_FULL_DEPLOYMENT"
            )

        if current_average_purchase_price > 0 and current_market_price > current_average_purchase_price:
            logger.info("[DCA][ALLOCATION][SKIP] Kill-switch active: market price is above average purchase price")
            return AllocationResult(
                spend_amount=0.0,
                dry_powder_delta=nominal_investment_amount,
                action_description="AVERAGE_PRICE_PROTECTION_HALT"
            )

        investment_multiplier = 1.0
        if current_average_purchase_price > 0 and current_market_price <= current_average_purchase_price:
            distance_from_pru_percent = (current_average_purchase_price - current_market_price) / current_average_purchase_price
            investment_multiplier = 1.0 + (distance_from_pru_percent * price_elasticity_aggressiveness)
            logger.debug("[DCA][ALLOCATION][SCALING] Elasticity multiplier calculated: %s", investment_multiplier)

        if current_macro_ema > 0 and current_market_price > current_macro_ema:
            base_allocation_amount = nominal_investment_amount * 0.5
            target_spend_amount = base_allocation_amount * investment_multiplier
            action_prefix = "CONSERVATIVE_RETENTION_SCALED"
        elif current_macro_ema > 0 and current_market_price <= current_macro_ema:
            base_allocation_amount = nominal_investment_amount + (current_dry_powder_reserve * 0.5)
            target_spend_amount = base_allocation_amount * investment_multiplier
            action_prefix = "AGGRESSIVE_DIP_ACCUMULATION_SCALED"
        else:
            target_spend_amount = nominal_investment_amount
            action_prefix = "FALLBACK_NOMINAL_STRATEGY"

        max_available_liquidity = nominal_investment_amount + current_dry_powder_reserve
        actual_spend_amount = min(target_spend_amount, max_available_liquidity)
        dry_powder_delta = nominal_investment_amount - actual_spend_amount

        logger.info(
            "[DCA][ALLOCATION][RESULT] Action: %s | Spend: %s | Multiplier: %s",
            action_prefix,
            actual_spend_amount,
            investment_multiplier
        )

        return AllocationResult(
            spend_amount=actual_spend_amount,
            dry_powder_delta=dry_powder_delta,
            action_description=f"{action_prefix}_(X:{investment_multiplier:.2f})"
        )
