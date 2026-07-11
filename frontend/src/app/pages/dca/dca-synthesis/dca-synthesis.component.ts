import { DecimalPipe, NgIf } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { CardModule } from 'primeng/card';
import { OptionalNumberPipe } from '../../../core/optional-number.pipe';
import { DcaOrderPayload, DcaStrategyPayload, TradingEquityCurvePointPayload, YieldMetrics } from '../../../core/models';
import { SparklineComponent } from '../../../widgets/sparkline/sparkline.component';
import { hasExecutedDcaOrders } from '../dca-execution.utils';
import { buildEffectiveSmartAverageUnitPriceSeries } from '../dca-strategy-path-projection/data/dca-strategy-path-projection-series-data.utils';
import { resolveHistoricalBacktestStartExecutionPrice, resolveProjectedLivePriceMultiplier } from '../dca-price-scaling.utils';

export interface DurationSummary {
    totalWeeks: number;
    totalMonths: number;
    executedInstallments: number;
    totalInstallments: number;
    daysRemaining: number;
}

export interface FinalProjections {
    smartAverageUnitPrice: number | null;
    standardAverageUnitPrice: number | null;
    alphaPercentage: number | null;
    accumulatedTargetAssetQuantity: number | null;
}

export interface BullPortfolioProjections {
    totalValue: number | null;
    multiplier: number | null;
    smartAlphaUsd: number | null;
    bearValue: number | null;
    standardTotalValue: number | null;
    lumpSumTotalValue: number | null;
    dumbVariancePercentage: number | null;
    lumpSumVariancePercentage: number | null;
}

export interface ProjectedSavingsDisplay {
    live: number | null;
    bear: number | null;
    bull: number | null;
    bearPriceTarget: number | null;
    bullPriceTarget: number | null;
    livePrice: number | null;
    cryptoAmount: number | null;
}

export interface YieldAccrualMetrics {
    dailyYield: number;
    monthlyYield: number;
    extraStepsFunded: number;
}

@Component({
    standalone: true,
    selector: 'app-dca-synthesis',
    imports: [DecimalPipe, NgIf, CardModule, SparklineComponent, OptionalNumberPipe],
    templateUrl: './dca-synthesis.component.html'
})
export class DcaSynthesisComponent {
    public strategy = input.required<DcaStrategyPayload>();

    public readonly availableDryPowder = computed<number>(() => this.strategy().available_dry_powder ?? 0);

    public readonly hasExecutedOrders = computed<boolean>(() => hasExecutedDcaOrders(this.strategy()));

    public readonly finalProjections = computed<FinalProjections>(() => {
        const emptyProjections: FinalProjections = {
            smartAverageUnitPrice: null,
            standardAverageUnitPrice: null,
            alphaPercentage: null,
            accumulatedTargetAssetQuantity: null
        };

        if (!this.hasExecutedOrders()) {
            return emptyProjections;
        }

        const strat: DcaStrategyPayload = this.strategy();
        const backtestMetadata = strat.historical_backtest_payload?.metadata;
        if (!backtestMetadata) {
            return emptyProjections;
        }

        const priceMultiplier: number = resolveProjectedLivePriceMultiplier(strat);

        const smartAverageUnitPrice: number = backtestMetadata.final_smart_average_unit_price * priceMultiplier;
        const standardAverageUnitPrice: number = backtestMetadata.final_dumb_average_unit_price * priceMultiplier;
        const alphaPercentage: number =
            standardAverageUnitPrice > 0 ? ((standardAverageUnitPrice - smartAverageUnitPrice) / standardAverageUnitPrice) * 100 : 0;
        const accumulatedTargetAssetQuantity: number = strat.total_allocated_budget / smartAverageUnitPrice;

        return {
            smartAverageUnitPrice,
            standardAverageUnitPrice,
            alphaPercentage,
            accumulatedTargetAssetQuantity
        };
    });

    public readonly projectedSavings = computed<ProjectedSavingsDisplay>(() => {
        const strat: DcaStrategyPayload = this.strategy();
        const emptyProjectedSavings: ProjectedSavingsDisplay = {
            live: null,
            bear: null,
            bull: null,
            bearPriceTarget: null,
            bullPriceTarget: null,
            livePrice: strat.live_market_price > 0 ? strat.live_market_price : null,
            cryptoAmount: null
        };

        if (!this.hasExecutedOrders()) {
            return emptyProjectedSavings;
        }

        const projections: FinalProjections = this.finalProjections();
        if (
            projections.smartAverageUnitPrice === null ||
            projections.standardAverageUnitPrice === null ||
            projections.smartAverageUnitPrice <= 0 ||
            projections.standardAverageUnitPrice <= 0
        ) {
            return emptyProjectedSavings;
        }

        const baselineCryptoQuantity: number = strat.total_allocated_budget / projections.standardAverageUnitPrice;
        const smartCryptoQuantity: number = strat.total_allocated_budget / projections.smartAverageUnitPrice;
        const extraCryptoGained: number = smartCryptoQuantity - baselineCryptoQuantity;

        const livePrice: number = strat.live_market_price;
        const bearMarketBottomPrice: number = strat.previous_all_time_high_price * strat.bear_market_bottom_multiplier;
        const previousAmplitudeMultiplier: number = 1 + strat.previous_bull_market_amplitude_percentage / 100;
        const topPriceMultiplier: number = Math.pow(previousAmplitudeMultiplier, 1 / strat.curve_flattening_factor);
        const targetCycleTopPrice: number = bearMarketBottomPrice * topPriceMultiplier;
        const minimumProgressionAth: number = strat.previous_all_time_high_price * strat.minimum_bull_market_multiplier;
        const finalizedTargetPrice: number = Math.max(targetCycleTopPrice, minimumProgressionAth);

        return {
            live: extraCryptoGained * livePrice,
            bear: extraCryptoGained * bearMarketBottomPrice,
            bull: extraCryptoGained * finalizedTargetPrice,
            bearPriceTarget: bearMarketBottomPrice,
            bullPriceTarget: finalizedTargetPrice,
            livePrice: livePrice > 0 ? livePrice : null,
            cryptoAmount: extraCryptoGained
        };
    });

    public readonly bullPortfolioProjections = computed<BullPortfolioProjections>(() => {
        const emptyBullPortfolioProjections: BullPortfolioProjections = {
            totalValue: null,
            multiplier: null,
            smartAlphaUsd: null,
            bearValue: null,
            standardTotalValue: null,
            lumpSumTotalValue: null,
            dumbVariancePercentage: null,
            lumpSumVariancePercentage: null
        };

        if (!this.hasExecutedOrders()) {
            return emptyBullPortfolioProjections;
        }

        const strat: DcaStrategyPayload = this.strategy();
        const projections: FinalProjections = this.finalProjections();
        const savings: ProjectedSavingsDisplay = this.projectedSavings();

        if (projections.accumulatedTargetAssetQuantity === null || savings.bullPriceTarget === null || savings.bearPriceTarget === null) {
            return emptyBullPortfolioProjections;
        }

        const accumulatedTargetAssetQuantity: number = projections.accumulatedTargetAssetQuantity;
        const totalValue: number = accumulatedTargetAssetQuantity * savings.bullPriceTarget;
        const multiplier: number = strat.total_allocated_budget > 0 ? totalValue / strat.total_allocated_budget : 0;
        const smartAlphaUsd: number = (savings.cryptoAmount ?? 0) * savings.bullPriceTarget;
        const bearValue: number = accumulatedTargetAssetQuantity * savings.bearPriceTarget;

        const historicalStartPrice: number = resolveHistoricalBacktestStartExecutionPrice(strat);
        const priceMultiplier: number = resolveProjectedLivePriceMultiplier(strat);
        const scaledStartPrice: number = historicalStartPrice * priceMultiplier;

        const standardAverageUnitPrice: number = projections.standardAverageUnitPrice ?? 1;
        const standardTotalValue: number = (strat.total_allocated_budget / standardAverageUnitPrice) * savings.bullPriceTarget;
        const lumpSumTotalValue: number = (strat.total_allocated_budget / (scaledStartPrice > 0 ? scaledStartPrice : 1)) * savings.bullPriceTarget;

        const dumbVariancePercentage: number = totalValue > 0 ? ((standardTotalValue - totalValue) / totalValue) * 100 : 0;
        const lumpSumVariancePercentage: number = totalValue > 0 ? ((lumpSumTotalValue - totalValue) / totalValue) * 100 : 0;

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

    public readonly deployedAmount = computed<number>(() => this.strategy().total_deployed_amount ?? 0);

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
            executedInstallments: (strat.execution_orders ?? []).filter((order) => order.order_status === 'EXECUTED' || order.order_status === 'SKIPPED')
                .length,
            totalInstallments: strat.total_planned_executions,
            daysRemaining: Math.ceil(remainingMilliseconds / (1000 * 60 * 60 * 24))
        };
    });

    public readonly effectiveSmartAverageUnitPrice = computed<number | null>(() => {
        const strategyEntity = this.strategy();
        const effectiveSeries = buildEffectiveSmartAverageUnitPriceSeries(strategyEntity.execution_orders ?? []);
        if (effectiveSeries.length === 0) {
            return null;
        }
        const latestEffectivePoint = effectiveSeries[effectiveSeries.length - 1];
        return latestEffectivePoint.value > 0 ? latestEffectivePoint.value : null;
    });

    public readonly effectiveSmartAverageUnitPriceSparkline = computed<TradingEquityCurvePointPayload[]>(() => {
        const strategyEntity = this.strategy();
        return buildEffectiveSmartAverageUnitPriceSeries(strategyEntity.execution_orders ?? []).map((effectivePoint) => ({
            timestamp_milliseconds: effectivePoint.timestampMilliseconds,
            total_equity_value: effectivePoint.value
        }));
    });

    public readonly nominalMonthlyInstallment = computed<number>(() => {
        const strat = this.strategy();
        return strat.amount_per_execution_order;
    });

    public readonly progressPercentage = computed<number>(() => {
        const strat = this.strategy();
        return strat.total_allocated_budget > 0 ? (strat.total_deployed_amount / strat.total_allocated_budget) * 100 : 0;
    });

    public readonly totalBudget = computed<number>(() => this.strategy().total_allocated_budget ?? 0);

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
}
