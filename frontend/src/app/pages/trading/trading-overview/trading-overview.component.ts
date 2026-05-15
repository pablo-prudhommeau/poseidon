import { CommonModule } from '@angular/common';
import { Component, computed, inject, output } from '@angular/core';
import { Tooltip } from 'primeng/tooltip';
import { BlockchainCashBalancePayload, TradingEquityCurvePointPayload, TradingPositionPayload } from '../../../core/models';
import { OptionalNumberPipe } from '../../../core/optional-number.pipe';
import { WebSocketService } from '../../../core/websocket.service';
import { SparklineComponent } from '../../../widgets/sparkline/sparkline.component';
import { TradingPositionsTableComponent } from '../trading-positions-table/trading-positions-table.component';
import { TradingTradesTableComponent } from '../trading-trades-table/trading-trades-table.component';

type LiquidityBalanceCard = BlockchainCashBalancePayload & { isPlaceholder: boolean };

@Component({
    standalone: true,
    selector: 'app-trading-overview',
    imports: [CommonModule, OptionalNumberPipe, TradingPositionsTableComponent, TradingTradesTableComponent, SparklineComponent, Tooltip],
    templateUrl: './trading-overview.component.html',
    styleUrl: './trading-overview.component.css'
})
export class TradingOverviewComponent {
    private readonly webSocketService = inject(WebSocketService);

    readonly liquidity = computed(() => this.webSocketService.liquidity());

    readonly blockchainBalances = computed<BlockchainCashBalancePayload[]>(
        () => this.liquidity()?.blockchain_balances ?? this.webSocketService.portfolio()?.blockchain_balances ?? []
    );

    readonly liquiditySymbol = computed(() => this.liquidity()?.stablecoin_currency_symbol ?? '$');

    readonly blockchainBalanceCards = computed<LiquidityBalanceCard[]>(() => {
        const balances = this.blockchainBalances();
        const cards: LiquidityBalanceCard[] = balances.map((balance) => ({
            ...balance,
            isPlaceholder: false
        }));

        if (this.liquidity()?.mode !== 'LIVE') {
            return cards;
        }

        const minimumCards = this.liquidity()?.maximum_chain_count ?? 4;
        const placeholdersMissing = Math.max(0, minimumCards - cards.length);
        for (let index = 0; index < placeholdersMissing; index++) {
            cards.push({
                blockchain_network: `placeholder_${index + 1}`,
                stablecoin_symbol: '--',
                stablecoin_address: '',
                stablecoin_currency_symbol: this.liquiditySymbol(),
                balance_raw: 0,
                native_token_symbol: '--',
                native_token_balance_raw: 0,
                native_token_balance_usd: 0,
                isPlaceholder: true
            });
        }
        return cards;
    });
    readonly portfolio = computed(() => this.webSocketService.portfolio());

    readonly cash = computed<number | null>(() =>
        this.firstNonNull(
            this.mapNullable(this.liquidity(), (liquidity) => liquidity.available_cash_balance),
            this.mapNullable(this.portfolio(), (portfolio) => portfolio.available_cash_balance)
        )
    );
    readonly chainIcons: Record<string, string> = {
        solana: 'fa-bolt',
        ethereum: 'fa-diamond',
        bsc: 'fa-gem',
        base: 'fa-cube',
        avalanche: 'fa-snowflake'
    };
    readonly equity = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.total_equity_value));
    readonly holdings = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.active_holdings_value));
    readonly deployedPercentage = computed<number | null>(() => {
        const totalEquity = this.equity();
        const holdings = this.holdings();
        if (totalEquity === null || holdings === null) {
            return null;
        }
        if (totalEquity <= 0) {
            return 0;
        }
        return Math.min(100, (holdings / totalEquity) * 100);
    });

    readonly equitySpark = computed<TradingEquityCurvePointPayload[]>(() => this.portfolio()?.equity_curve ?? []);
    readonly hasLiveBalances = computed(() => this.blockchainBalances().length > 0);
    readonly liquidityMode = computed(() => this.mapNullable(this.liquidity(), (liquidity) => liquidity.mode));
    readonly liquiditySubtitle = computed(() => {
        const balances = this.blockchainBalances();
        if (balances.length > 0) {
            return `${balances[0].stablecoin_symbol} across ${balances.length} chain(s)`;
        }
        if (this.liquidityMode() === null) {
            return 'awaiting liquidity mode';
        }
        return 'available trading reserve';
    });
    readonly liquidityTitle = computed(() => {
        const liquidityMode = this.liquidityMode();
        if (liquidityMode === 'LIVE') {
            return 'on-chain liquidity';
        }
        if (liquidityMode === 'PAPER') {
            return 'paper reserve';
        }
        return 'reserve snapshot';
    });
    readonly liveChainCount = computed(() => this.blockchainBalances().length);
    readonly liveSlotCount = computed(() =>
        this.liquidity()?.mode === 'LIVE' ? (this.liquidity()?.maximum_chain_count ?? 4) : this.blockchainBalances().length
    );
    readonly positions = computed<TradingPositionPayload[]>(() => this.webSocketService.positions());

    readonly openPositionCount = computed(
        () => this.positions().filter((position) => position.position_phase === 'OPEN' || position.position_phase === 'PARTIAL').length
    );
    readonly openShadowChronicle = output<void>();
    readonly realized24h = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_24h));
    readonly realizedTotal = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_total));
    readonly shadowMeta = computed(() => this.webSocketService.shadowMeta());
    readonly shadowStatus = computed(() => this.portfolio()?.shadow_intelligence_status);
    readonly shadowPhase = computed(() => this.shadowStatus()?.phase ?? 'DISABLED');
    readonly shadowChronicleProfitFactor = computed<number | null>(() => {
        if (this.shadowPhase() === 'LEARNING') {
            return null;
        }
        return this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.chronicle_profit_factor);
    });

    readonly shadowChronicleProfitFactorThreshold = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.chronicle_profit_factor_threshold)
    );

    readonly shadowSparseExpectedValueUsd = computed<number | null>(() => {
        if (this.shadowPhase() === 'LEARNING') {
            return null;
        }
        return this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.sparse_expected_value_usd);
    });

    readonly shadowSparseExpectedValueUsdThreshold = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.sparse_expected_value_usd_threshold)
    );

    readonly shadowTradable = computed(() => {
        const chronicleProfitFactor = this.shadowChronicleProfitFactor();
        const chronicleThreshold = this.shadowChronicleProfitFactorThreshold();
        const sparseExpectedValue = this.shadowSparseExpectedValueUsd();
        const sparseExpectedValueThreshold = this.shadowSparseExpectedValueUsdThreshold();
        if (
            this.shadowPhase() !== 'ACTIVE' ||
            chronicleProfitFactor === null ||
            chronicleThreshold === null ||
            sparseExpectedValue === null ||
            sparseExpectedValueThreshold === null
        ) {
            return false;
        }
        return chronicleProfitFactor >= chronicleThreshold && sparseExpectedValue >= sparseExpectedValueThreshold;
    });

    readonly shadowRegimeLabel = computed(() => {
        if (this.shadowPhase() === 'DISABLED') {
            return 'disabled';
        }
        if (this.shadowPhase() === 'LEARNING') {
            return 'learning';
        }
        if (
            this.shadowPhase() === 'ACTIVE' &&
            (this.shadowChronicleProfitFactor() === null ||
                this.shadowChronicleProfitFactorThreshold() === null ||
                this.shadowSparseExpectedValueUsd() === null ||
                this.shadowSparseExpectedValueUsdThreshold() === null)
        ) {
            return 'syncing';
        }
        return this.shadowTradable() ? 'tradable' : 'bear meta';
    });

    readonly shadowAccentTextClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'text-purple-400';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'text-red-400';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'text-amber-400';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'text-purple-400';
        }
        return 'text-slate-400';
    });

    readonly shadowRequiredCount = computed(() => this.shadowStatus()?.required_outcome_count ?? 0);

    readonly shadowAwareResolvedCount = computed(() => {
        const count = this.shadowStatus()?.resolved_shadowing_and_cortex_inference_aware_outcome_count ?? 0;
        return Math.min(count, this.shadowRequiredCount());
    });

    readonly shadowAwareProgress = computed(() => {
        const aware = this.shadowAwareResolvedCount();
        const required = this.shadowRequiredCount();
        if (required <= 0) return 0;
        return Math.min(100, (aware / required) * 100);
    });

    readonly shadowAwareTooltip = computed(() => {
        return `Counts outcomes where the <span class="text-amber-300 font-bold uppercase tracking-widest text-[9px] mx-1">Statistical Intelligence</span> has been fully processed and synchronized, enabling high-fidelity metric computation.`;
    });

    readonly shadowCapitalVelocity = computed<number | null>(() => {
        if (this.shadowPhase() === 'LEARNING') {
            return null;
        }
        return this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.capital_velocity);
    });

    readonly shadowChronicleGeometryLabel = computed(() => {
        const meta = this.shadowMeta();
        if (!meta) {
            return '—';
        }
        return `momentum ${this.formatShadowMetricLookbackDays(meta.chronicle_profit_factor_lookback_days)}d ${meta.chronicle_profit_factor_bucket_width_seconds}s p${meta.chronicle_profit_factor_moving_average_period}`;
    });

    readonly shadowChronicleGeometryTooltip = computed(() => {
        const meta = this.shadowMeta();
        if (!meta) {
            return '';
        }
        const lookback = this.formatShadowMetricLookbackDays(meta.chronicle_profit_factor_lookback_days);
        const bucket = meta.chronicle_profit_factor_bucket_width_seconds;
        const period = meta.chronicle_profit_factor_moving_average_period;
        return `Measures the <span class="text-purple-300 font-bold uppercase tracking-widest text-[9px] mx-1">momentum</span> by averaging the <span class="text-slate-200 font-bold mx-0.5">Profit Factor</span> across ${period} sequential ${bucket}s timeframes, scanning a ${lookback}-day historical depth.`;
    });

    readonly shadowChronicleProfitFactorProgress = computed(() => {
        const threshold = this.shadowChronicleProfitFactorThreshold();
        const value = this.shadowChronicleProfitFactor();
        if (threshold === null || value === null || threshold <= 0) {
            return null;
        }
        return Math.min(100, (value / threshold) * 100);
    });

    readonly shadowRequiredHours = computed(() => this.shadowStatus()?.required_hours ?? 0);

    readonly shadowElapsedHours = computed(() => {
        const elapsed = this.shadowStatus()?.elapsed_hours ?? 0;
        return Math.min(elapsed, this.shadowRequiredHours());
    });

    readonly shadowExpectedValue = computed<number | null>(() => {
        if (this.shadowPhase() === 'LEARNING') {
            return null;
        }
        return this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.expected_value_usd);
    });

    readonly shadowHoursProgress = computed(() => {
        const progress = this.shadowStatus()?.hours_progress_percentage ?? 0;
        return Math.min(progress, 100);
    });

    readonly shadowOutcomeProgress = computed(() => this.shadowStatus()?.outcome_progress_percentage ?? 0);

    readonly shadowProgressClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'bg-purple-400';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'bg-red-400';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'bg-amber-400';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'bg-purple-400';
        }
        return 'bg-slate-700';
    });

    readonly shadowRegimeClasses = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'bg-purple-500/10 text-purple-300 border-purple-500/20';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'bg-red-500/10 text-red-300 border-red-500/20';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'bg-amber-500/10 text-amber-300 border-amber-500/20';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'bg-purple-500/10 text-purple-300 border-purple-500/20';
        }
        return 'bg-slate-500/10 text-slate-300 border-slate-500/20';
    });

    readonly shadowSparseExpectedValueGeometryLabel = computed(() => {
        const meta = this.shadowMeta();
        if (!meta) {
            return '—';
        }
        return `sparse ev ${this.formatShadowMetricLookbackDays(meta.sparse_expected_value_lookback_days)}d ${meta.sparse_expected_value_bucket_width_seconds}s p${meta.sparse_expected_value_moving_average_period}`;
    });

    readonly shadowSparseExpectedValueGeometryTooltip = computed(() => {
        const meta = this.shadowMeta();
        if (!meta) {
            return '';
        }
        const lookback = this.formatShadowMetricLookbackDays(meta.sparse_expected_value_lookback_days);
        const bucket = meta.sparse_expected_value_bucket_width_seconds;
        const period = meta.sparse_expected_value_bucket_width_seconds;
        return `Measures the <span class="text-purple-300 font-bold uppercase tracking-widest text-[9px] mx-1">Sparse EV</span> by averaging the <span class="text-slate-200 font-bold mx-0.5">Expected Value</span> across ${period} sequential ${bucket}s timeframes, scanning a ${lookback}-day historical depth.`;
    });

    readonly shadowSparseExpectedValueProgress = computed(() => {
        const threshold = this.shadowSparseExpectedValueUsdThreshold();
        const value = this.shadowSparseExpectedValueUsd();
        if (threshold === null || value === null) {
            return null;
        }
        if (value >= threshold) {
            return 100;
        }
        const worstValue: number = -15.0;
        const progress: number = Math.min(100, Math.max(0, (value / worstValue) * 100));
        return progress;
    });

    readonly shadowTitleTextClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'text-purple-300';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'text-red-300';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'text-amber-300';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'text-purple-300';
        }
        return 'text-slate-300';
    });

    readonly shadowTotalResolvedCount = computed(() => {
        const count = this.shadowStatus()?.resolved_outcome_count ?? 0;
        return Math.min(count, this.shadowRequiredCount());
    });

    readonly shadowTotalProgress = computed(() => {
        const total = this.shadowTotalResolvedCount();
        const required = this.shadowRequiredCount();
        if (required <= 0) return 0;
        return Math.min(100, (total / required) * 100);
    });

    readonly shadowTotalTooltip = computed(() => {
        return `Represents outcomes serving as the <span class="text-slate-200 font-bold uppercase tracking-widest text-[9px] mx-1">Statistical Baseline</span>; they cannot be shadowed yet as they are used to calibrate the engine before activation.`;
    });

    readonly shadowWinRate = computed<number | null>(() => {
        if (this.shadowPhase() === 'LEARNING') {
            return null;
        }
        return this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.win_rate_percentage);
    });

    readonly shouldShowReserveModeCard = computed(() => this.liquidityMode() === 'PAPER');

    readonly shouldShowLiquiditySyncCard = computed(() => !this.hasLiveBalances() && !this.shouldShowReserveModeCard());

    readonly unrealized = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.unrealized_profit_and_loss));

    formatMultiplier(value: number | null | undefined): string {
        if (value === null || value === undefined || !Number.isFinite(value)) {
            return '—';
        }
        if (value >= 900) {
            return '999+';
        }
        return value.toFixed(2);
    }

    formatShadowMetricLookbackDays(days: number): string {
        if (Number.isInteger(days)) {
            return String(days);
        }
        const rounded = Math.round(days * 10) / 10;
        return rounded % 1 === 0 ? String(Math.round(rounded)) : rounded.toFixed(1);
    }

    isNonNegative(value: number | null): boolean {
        if (value === null) {
            return false;
        }
        return value >= 0;
    }

    rangeArray(length: number): number[] {
        return Array.from({ length }, (_, index) => index);
    }

    private firstNonNull(...values: Array<number | null>): number | null {
        for (const value of values) {
            if (value !== null) {
                return value;
            }
        }
        return null;
    }

    private mapNullable<TSource, TProjected>(value: TSource | null | undefined, mapper: (value: TSource) => TProjected): Exclude<TProjected, undefined> | null {
        if (value === null || value === undefined) {
            return null;
        }
        const projected = mapper(value);
        return projected === undefined ? null : (projected as Exclude<TProjected, undefined>);
    }
}
