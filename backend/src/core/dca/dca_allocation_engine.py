from src.core.structures.structures import AllocationResult


class DcaAllocationEngine:

    @staticmethod
    def calculate_allocation(
            nominal_tranche: float,
            current_dry_powder: float,
            current_price: float,
            current_macro_ema: float,
            current_pru: float,
            is_last_execution: bool,
            pru_elasticity_factor: float
    ) -> AllocationResult:

        if is_last_execution:
            return AllocationResult(
                spend_amount=nominal_tranche + current_dry_powder,
                dry_powder_delta=-current_dry_powder,
                action_description="FINAL_DEPLOYMENT"
            )

        if current_pru > 0 and current_price > current_pru:
            return AllocationResult(
                spend_amount=0.0,
                dry_powder_delta=nominal_tranche,
                action_description="KILL_SWITCH_ACTIVE"
            )

        multiplier = 1.0
        if current_pru > 0 and current_price <= current_pru:
            distance_pct = (current_pru - current_price) / current_pru
            multiplier = 1.0 + (distance_pct * pru_elasticity_factor)

        if current_macro_ema > 0 and current_price > current_macro_ema:
            base_amount = nominal_tranche * 0.5
            target_spend = base_amount * multiplier
            action_prefix = "50%_RETENTION_SCALED"
        elif current_macro_ema > 0 and current_price <= current_macro_ema:
            base_amount = nominal_tranche + (current_dry_powder * 0.5)
            target_spend = base_amount * multiplier
            action_prefix = "DIP_ACCUMULATION_SCALED"
        else:
            target_spend = nominal_tranche
            action_prefix = "FALLBACK_NOMINAL"

        max_available = nominal_tranche + current_dry_powder
        actual_spend = min(target_spend, max_available)
        dry_powder_delta = nominal_tranche - actual_spend

        return AllocationResult(
            spend_amount=actual_spend,
            dry_powder_delta=dry_powder_delta,
            action_description=f"{action_prefix}_(M:{multiplier:.2f}x)"
        )
