import {Component, computed, input} from '@angular/core';
import {DecimalPipe, NgIf} from '@angular/common';
import {CardModule} from 'primeng/card';
import {SparklineComponent} from '../../../widgets/sparkline/sparkline.component';
import {DcaOrderPayload, DcaStrategyPayload, TradingEquityCurvePointPayload, MacroProjectionSavings, YieldMetrics} from '../../../core/models';

export interface DurationSummary {
    totalWeeks: number;
    totalMonths: number;
    totalInstallments: number;
    daysRemaining: number;
}

export interface FinalProjections {
    smartPru: number;
    standardPru: number;
    alphaPercentage: number;
    accumulatedAsset: number;
}

export interface BullPortfolioProjections {
    totalValue: number;
    multiplier: number;
    smartAlphaUsd: number;
    bearValue: number;
    standardTotalValue: number;
    lumpSumTotalValue: number;
    dumbVariancePercentage: number;
    lumpSumVariancePercentage: number;
}

export interface YieldAccrualMetrics {
    dailyYield: number;
    monthlyYield: number;
    extraStepsFunded: number;
}

@Component({
    standalone: true,
    selector: 'app-dca-synthesis',
    imports: [DecimalPipe, NgIf, CardModule, SparklineComponent],
    templateUrl: './dca-synthesis.component.html'
})
export class DcaSynthesisComponent {
    public strategy = input.required<DcaStrategyPayload>();

    public readonly deployedAmount = computed<number>(() => this.strategy().total_deployed_amount ?? 0);
    public readonly totalBudget = computed<number>(() => this.strategy().total_allocated_budget ?? 0);
    public readonly currentAveragePurchasePrice = computed<number>(() => this.strategy().average_purchase_price ?? 0);

    public readonly progressPercentage = computed<number>(() => {
        const strat = this.strategy();
        return strat.total_allocated_budget > 0 ? (strat.total_deployed_amount / strat.total_allocated_budget) * 100 : 0;
    });

    public readonly availableDryPowder = computed<number>(() => this.strategy().available_dry_powder ?? 0);

    public readonly durationSummary = computed<DurationSummary>(() => {
        const strat = this.strategy();
        const start = new Date(strat.strategy_start_date);
        const end = new Date(strat.strategy_end_date);
        const now = new Date();

        const diffMilliseconds = end.getTime() - start.getTime();
        const remainingMilliseconds = Math.max(0, end.getTime() - now.getTime());

        return {
            totalWeeks: Math.ceil(diffMilliseconds / (1000 * 60 * 60 * 24 * 7)),
            totalMonths: Math.max(1, Math.round(diffMilliseconds / (1000 * 60 * 60 * 24 * 30.44))),
            totalInstallments: strat.total_planned_executions,
            daysRemaining: Math.ceil(remainingMilliseconds / (1000 * 60 * 60 * 24))
        };
    });

    public readonly nominalMonthlyInstallment = computed<number>(() => {
        const strat = this.strategy();
        return strat.amount_per_execution_order;
    });

    public readonly finalProjections = computed<FinalProjections>(() => {
        const strat = this.strategy();
        const backtestMetadata = strat.historical_backtest_payload?.metadata;
        if (!backtestMetadata) {
            return {smartPru: 0, standardPru: 0, alphaPercentage: 0, accumulatedAsset: 0};
        }

        const historicalStartPrice = strat.historical_backtest_payload.dumb_dca_series?.[0]?.execution_price ?? 0;
        const livePrice = this.calculateCurrentLivePrice(strat);
        const priceMultiplier = (livePrice > 0 && historicalStartPrice > 0) ? (livePrice / historicalStartPrice) : 1;

        const smartPru = backtestMetadata.final_smart_average_unit_price * priceMultiplier;
        const standardPru = backtestMetadata.final_dumb_average_unit_price * priceMultiplier;
        const alphaPercentage = standardPru > 0 ? ((standardPru - smartPru) / standardPru) * 100 : 0;
        const accumulatedAsset = strat.total_allocated_budget / smartPru;

        return {
            smartPru,
            standardPru,
            alphaPercentage,
            accumulatedAsset
        };
    });

    public readonly bullPortfolioProjections = computed<BullPortfolioProjections>(() => {
        const strat = this.strategy();
        const projections = this.finalProjections();
        const savings = this.projectedSavings();

        const totalValue = projections.accumulatedAsset * savings.bullPriceTarget;
        const multiplier = strat.total_allocated_budget > 0 ? totalValue / strat.total_allocated_budget : 0;
        const smartAlphaUsd = savings.cryptoAmount * savings.bullPriceTarget;
        const bearValue = projections.accumulatedAsset * savings.bearPriceTarget;

        const historicalStartPrice = strat.historical_backtest_payload.dumb_dca_series?.[0]?.execution_price ?? 0;
        const livePrice = this.calculateCurrentLivePrice(strat);
        const priceMultiplier = (livePrice > 0 && historicalStartPrice > 0) ? (livePrice / historicalStartPrice) : 1;
        const scaledStartPrice = historicalStartPrice * priceMultiplier;
        const backtestMetadata = strat.historical_backtest_payload?.metadata;

        const standardTotalValue = (strat.total_allocated_budget / (projections.standardPru || 1)) * savings.bullPriceTarget;
        const lumpSumTotalValue = (strat.total_allocated_budget / (scaledStartPrice || 1)) * savings.bullPriceTarget;

        const dumbVariancePercentage = totalValue > 0 ? ((standardTotalValue - totalValue) / totalValue) * 100 : 0;
        const lumpSumVariancePercentage = totalValue > 0 ? ((lumpSumTotalValue - totalValue) / totalValue) * 100 : 0;

        return {
            totalValue,
            multiplier,
            smartAlphaUsd,
            bearValue,
            standardTotalValue,
            lumpSumTotalValue,
            dumbVariancePercentage,
            lumpSumVariancePercentage
        };
    });

    public readonly yieldAccrualMetrics = computed<YieldAccrualMetrics>(() => {
        const strat = this.strategy();
        const metrics = this.yieldMetrics();
        const totalProjectedYield = metrics.realized + metrics.projectedRemaining;

        const start = new Date(strat.strategy_start_date).getTime();
        const end = new Date(strat.strategy_end_date).getTime();
        const durationDays = Math.max(1, (end - start) / (1000 * 60 * 60 * 24));

        const dailyYield = totalProjectedYield / durationDays;
        const monthlyYield = dailyYield * 30.44;
        const extraStepsFunded = strat.amount_per_execution_order > 0 ? metrics.realized / strat.amount_per_execution_order : 0;

        return {
            dailyYield,
            monthlyYield,
            extraStepsFunded
        };
    });

    private calculateCurrentLivePrice(strategy: DcaStrategyPayload): number {
        if (strategy.live_market_price > 0) {
            return strategy.live_market_price;
        }

        if (!strategy.execution_orders || strategy.execution_orders.length === 0) {
            return 0;
        }

        const executedOrders = strategy.execution_orders
            .filter((order: DcaOrderPayload) => order.order_status === 'EXECUTED' && order.actual_execution_price != null)
            .sort((orderA, orderB) => new Date(orderB.executed_at!).getTime() - new Date(orderA.executed_at!).getTime());

        return executedOrders.length > 0 ? (executedOrders[0].actual_execution_price ?? 0) : 0;
    }

    public readonly purchasePriceSparkline = computed<TradingEquityCurvePointPayload[]>(() => {
        const strat = this.strategy();
        if (!strat.execution_orders) {
            return [];
        }

        return strat.execution_orders
            .filter((order: DcaOrderPayload) => order.order_status === 'EXECUTED' && order.actual_execution_price != null && order.executed_at != null)
            .sort((a, b) => new Date(a.executed_at!).getTime() - new Date(b.executed_at!).getTime())
            .map((order: DcaOrderPayload) => ({
                timestamp_milliseconds: new Date(order.executed_at!).getTime(),
                total_equity_value: order.actual_execution_price as number
            }));
    });

    public readonly yieldMetrics = computed<YieldMetrics>(() => {
        const strat = this.strategy();
        const realized = strat.realized_aave_yield_amount;
        const now = Date.now();
        const end = strat.strategy_end_date ? new Date(strat.strategy_end_date).getTime() : now;
        const start = strat.strategy_start_date ? new Date(strat.strategy_start_date).getTime() : now;
        const effectiveStartForProjection = Math.max(now, start);
        const remainingYears = Math.max(0, (end - effectiveStartForProjection) / (1000 * 60 * 60 * 24 * 365.25));
        const unspentBudget = strat.total_allocated_budget - strat.total_deployed_amount;
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
        const projections = this.finalProjections();
        if (projections.smartPru <= 0 || projections.standardPru <= 0) {
            return {
                live: 0, bear: 0, bull: 0,
                bearPriceTarget: 0, bullPriceTarget: 0,
                livePrice: 0, cryptoAmount: 0
            };
        }

        const baselineCryptoQuantity = strat.total_allocated_budget / projections.standardPru;
        const smartCryptoQuantity = strat.total_allocated_budget / projections.smartPru;
        const extraCryptoGained = smartCryptoQuantity - baselineCryptoQuantity;

        const livePrice = strat.live_market_price;
        const bearMarketBottomPrice = strat.previous_all_time_high_price * strat.bear_market_bottom_multiplier;
        const previousAmplitudeMultiplier = 1 + (strat.previous_bull_market_amplitude_percentage / 100);
        const topPriceMultiplier = Math.pow(previousAmplitudeMultiplier, 1 / strat.curve_flattening_factor);
        const targetCycleTopPrice = bearMarketBottomPrice * topPriceMultiplier;
        const minimumProgressionAth = strat.previous_all_time_high_price * strat.minimum_bull_market_multiplier;
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