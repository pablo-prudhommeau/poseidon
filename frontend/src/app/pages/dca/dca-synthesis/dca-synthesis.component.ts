import {Component, computed, input} from '@angular/core';
import {DecimalPipe, NgIf} from '@angular/common';
import {CardModule} from 'primeng/card';
import {PnlBadgeComponent} from '../../../widgets/pnl-badge/pnl-badge.component';
import {SparklineComponent} from '../../../widgets/sparkline/sparkline.component';
import {DcaOrder, DcaStrategy, EquityCurvePoint, MacroProjectionSavings, YieldMetrics} from '../../../core/models';

@Component({
    standalone: true,
    selector: 'app-dca-synthesis',
    imports: [DecimalPipe, NgIf, CardModule, PnlBadgeComponent, SparklineComponent],
    templateUrl: './dca-synthesis.component.html'
})
export class DcaSynthesisComponent {
    public strategy = input.required<DcaStrategy>();

    public readonly deployedAmount = computed<number>(() => this.strategy().deployed_amount ?? 0);
    public readonly totalBudget = computed<number>(() => this.strategy().total_budget ?? 0);
    public readonly currentAveragePurchasePrice = computed<number>(() => this.strategy().average_purchase_price ?? 0);

    public readonly progressPercentage = computed<number>(() => {
        const strat = this.strategy();
        return strat.total_budget > 0 ? (strat.deployed_amount / strat.total_budget) * 100 : 0;
    });

    public readonly purchasePriceSparkline = computed<EquityCurvePoint[]>(() => {
        const strat = this.strategy();
        if (!strat.orders) {
            return [];
        }

        return strat.orders
            .filter((order: DcaOrder) => order.status === 'EXECUTED' && order.execution_price != null && order.executed_at != null)
            .sort((a, b) => new Date(a.executed_at!).getTime() - new Date(b.executed_at!).getTime())
            .map((order: DcaOrder) => ({
                timestamp: new Date(order.executed_at!).getTime(),
                equity: order.execution_price as number
            }));
    });

    public readonly yieldMetrics = computed<YieldMetrics>(() => {
        const strat = this.strategy();
        const realized = strat.realized_aave_yield;
        const now = Date.now();
        const end = strat.end_date ? new Date(strat.end_date).getTime() : now;
        const start = strat.start_date ? new Date(strat.start_date).getTime() : now;
        const effectiveStartForProjection = Math.max(now, start);
        const remainingYears = Math.max(0, (end - effectiveStartForProjection) / (1000 * 60 * 60 * 24 * 365.25));
        const unspentBudget = strat.total_budget - strat.deployed_amount;
        const apyFactor = strat.live_aave_apy;
        const projectedRemaining = unspentBudget * apyFactor * remainingYears;

        return {
            realized,
            projectedRemaining,
            apy: apyFactor * 100
        };
    });

    public readonly projectedSavings = computed<MacroProjectionSavings>(() => {
        const strat = this.strategy();
        const metadata = strat.backtest_payload.metadata;
        const baselineCryptoQuantity = strat.total_budget / metadata.final_dumb_average_unit_price;
        const smartCryptoQuantity = strat.total_budget / metadata.final_smart_average_unit_price;
        const extraCryptoGained = smartCryptoQuantity - baselineCryptoQuantity;
        const livePrice = strat.live_market_price;
        const bearMarketBottomPrice = strat.previous_ath * strat.bear_bottom_multiplier;
        const previousAmplitudeMultiplier = 1 + (strat.previous_bull_amplitude_pct / 100);
        const topPriceMultiplier = Math.pow(previousAmplitudeMultiplier, 1 / strat.flattening_factor);
        const targetCycleTopPrice = bearMarketBottomPrice * topPriceMultiplier;
        const minimumProgressionAth = strat.previous_ath * strat.minimum_bull_multiplier;
        const finalizedTargetPrice = Math.max(targetCycleTopPrice, minimumProgressionAth);
        return {
            live: extraCryptoGained * livePrice,
            bear: extraCryptoGained * bearMarketBottomPrice,
            bull: extraCryptoGained * finalizedTargetPrice,
            bearPriceTarget: bearMarketBottomPrice,
            bullPriceTarget: finalizedTargetPrice,
            livePrice: livePrice,
            cryptoAmount: extraCryptoGained
        };
    });
}