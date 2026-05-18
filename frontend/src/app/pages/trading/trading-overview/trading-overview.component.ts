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
    readonly shadowRegime = computed(() => this.webSocketService.shadowRegime());
    readonly shadowStatus = computed(() => this.shadowRegime());
    readonly shadowGateRequiredCount = computed(() => this.shadowStatus()?.required_shadow_gate_outcome_count ?? 0);

    readonly shadowGateReadyForCortex = computed(() => {
        const required = this.shadowGateRequiredCount();
        if (required <= 0) {
            return true;
        }
        return (this.shadowStatus()?.resolved_shadowing_and_cortex_inference_aware_outcome_count ?? 0) >= required;
    });
    readonly cortexGateEligibleProgress = computed(() => {
        if (!this.shadowGateReadyForCortex()) {
            return 0;
        }
        return Math.min(this.shadowStatus()?.cortex_training_progress_percentage ?? 0, 100);
    });
    readonly cortexTrainingRequiredCount = computed(() => this.shadowStatus()?.required_cortex_training_outcome_count ?? 0);
    readonly cortexGateEligibleResolvedCount = computed(() => {
        if (!this.shadowGateReadyForCortex()) {
            return 0;
        }
        const count = this.shadowStatus()?.resolved_shadowing_and_cortex_inference_aware_outcome_count ?? 0;
        return Math.min(count, this.cortexTrainingRequiredCount());
    });
    readonly cortexGateEligibleTooltip = computed(() => {
        return `Counts resolved non-staled outcomes with complete shadow context and labels; accumulation starts only after the <span class="text-amber-300 font-bold uppercase tracking-widest text-[9px] mx-1">shadow gate threshold</span> is reached.`;
    });
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

    readonly shadowPhase = computed(() => this.shadowRegime()?.phase ?? 'SYNCING');

    readonly shadowRegimeLabel = computed(() => {
        return this.shadowPhase().toLowerCase();
    });

    readonly shadowAccentTextClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'text-purple-400';
        }
        if (this.shadowRegimeLabel() === 'shadowing') {
            return 'text-amber-400';
        }
        if (this.shadowRegimeLabel() === 'cortexing') {
            return 'text-pink-400';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'text-slate-300';
        }
        return 'text-slate-400';
    });

    readonly shadowChronicleGeometryLabel = computed(() => {
        const regime = this.shadowRegime();
        if (!regime) {
            return '—';
        }
        return `pf sma · ${this.formatShadowMetricLookbackDays(regime.chronicle_profit_factor_lookback_days)}d · ${regime.chronicle_profit_factor_bucket_width_seconds}s · ${regime.chronicle_profit_factor_moving_average_period} samples`;
    });

    readonly shadowChronicleGeometryTooltip = computed(() => {
        const regime = this.shadowRegime();
        if (!regime) {
            return '';
        }
        const lookback = this.formatShadowMetricLookbackDays(regime.chronicle_profit_factor_lookback_days);
        const bucket = regime.chronicle_profit_factor_bucket_width_seconds;
        const period = regime.chronicle_profit_factor_moving_average_period;
        const sampleWindow = this.formatSampleWindowDuration(period, bucket);
        return `Tracks the <span class="text-purple-200 font-black uppercase tracking-widest text-[9px] mx-1">profit factor regime</span>: gross winning dollars divided by gross losing dollars, smoothed over <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${period}</span> non-empty verdict buckets of <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${bucket}s</span> each (about <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${sampleWindow}</span> of samples), inside a rolling <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${lookback}-day</span> history.`;
    });
    readonly shadowMetricsReady = computed(() => {
        const regime = this.shadowRegime();
        if (regime?.phase === 'TRADABLE' || regime?.phase === 'CORTEXING') {
            return true;
        }
        const status = this.shadowStatus();
        if (!status) {
            return false;
        }
        const shadowingReady = status.required_shadowing_outcome_count <= 0 || status.resolved_outcome_count >= status.required_shadowing_outcome_count;
        const shadowGateReady =
            status.required_shadow_gate_outcome_count <= 0 ||
            status.resolved_shadowing_and_cortex_inference_aware_outcome_count >= status.required_shadow_gate_outcome_count;
        const hoursReady = status.required_hours <= 0 || status.elapsed_hours >= status.required_hours;
        return shadowingReady && shadowGateReady && hoursReady;
    });

    readonly shadowChronicleProfitFactor = computed<number | null>(() => {
        if (!this.shadowMetricsReady()) {
            return null;
        }
        return this.mapNullable(this.shadowRegime(), (shadowRegime) => shadowRegime.chronicle_profit_factor);
    });

    readonly shadowChronicleProfitFactorThreshold = computed<number | null>(() =>
        this.mapNullable(this.shadowRegime(), (shadowRegime) => shadowRegime.chronicle_profit_factor_threshold)
    );

    readonly shadowRegimeGateEnabled = computed(() => this.shadowRegime()?.shadow_regime_gate_enabled ?? true);

    readonly shadowChronicleProfitFactorProgress = computed(() => {
        if (!this.shadowRegimeGateEnabled()) {
            return 100;
        }
        const threshold = this.shadowChronicleProfitFactorThreshold();
        const value = this.shadowChronicleProfitFactor();
        if (threshold === null || value === null || threshold <= 0) {
            return null;
        }
        return Math.min(100, (value / threshold) * 100);
    });

    readonly shadowLearningProgressVisible = computed(() => {
        return this.shadowRegimeLabel() === 'shadowing' || this.shadowRegimeLabel() === 'cortexing';
    });

    readonly shadowLearningDone = computed(() => {
        return this.shadowLearningProgressVisible() && this.shadowMetricsReady();
    });

    readonly shadowChronicleProfitFactorBarClass = computed(() => {
        const progress = this.shadowChronicleProfitFactorProgress();
        if (progress === null) {
            return 'bg-slate-700';
        }
        if (this.shadowLearningDone()) {
            return 'bg-slate-200';
        }
        return progress >= 100 ? 'bg-purple-400' : 'bg-red-400';
    });

    readonly shadowChronicleProfitFactorFloorLabel = computed(() => {
        if (!this.shadowRegimeGateEnabled()) {
            return '-∞';
        }
        const threshold = this.shadowChronicleProfitFactorThreshold();
        return threshold === null ? '—' : threshold.toFixed(2);
    });

    readonly shadowChronicleProfitFactorValueClass = computed(() => {
        const progress = this.shadowChronicleProfitFactorProgress();
        if (progress === null) {
            return 'text-slate-200';
        }
        if (this.shadowLearningDone()) {
            return 'text-slate-100';
        }
        return progress >= 100 ? 'text-purple-400' : 'text-red-400';
    });

    readonly shadowRequiredHours = computed(() => this.shadowStatus()?.required_hours ?? 0);

    readonly shadowElapsedHours = computed(() => {
        const elapsed = this.shadowStatus()?.elapsed_hours ?? 0;
        return Math.min(elapsed, this.shadowRequiredHours());
    });

    readonly shadowExpectedPnlVelocity = computed<number | null>(() => {
        if (!this.shadowMetricsReady()) {
            return null;
        }
        return this.mapNullable(this.shadowRegime(), (shadowRegime) => shadowRegime.expected_pnl_velocity);
    });

    readonly shadowExpectedValue = computed<number | null>(() => {
        if (!this.shadowMetricsReady()) {
            return null;
        }
        return this.mapNullable(this.shadowRegime(), (shadowRegime) => shadowRegime.expected_value_usd);
    });

    readonly shadowExpectedValueClass = computed(() => {
        const value = this.shadowExpectedValue();
        if (value === null) {
            return 'text-slate-200';
        }
        if (this.shadowLearningDone()) {
            return 'text-slate-100';
        }
        return this.isNonNegative(value) ? 'text-purple-400' : 'text-red-400';
    });

    readonly shadowGateEligibleProgress = computed(() => {
        return Math.min(this.shadowStatus()?.shadowing_gate_progress_percentage ?? 0, 100);
    });

    readonly shadowGateEligibleResolvedCount = computed(() => {
        const count = this.shadowStatus()?.resolved_shadowing_and_cortex_inference_aware_outcome_count ?? 0;
        return Math.min(count, this.shadowGateRequiredCount());
    });

    readonly shadowGateEligibleTooltip = computed(() => {
        return `Counts resolved outcomes with complete <span class="text-amber-300 font-bold uppercase tracking-widest text-[9px] mx-1">shadowing summary + metrics</span>; these are eligible to activate the shadow regime gate.`;
    });

    readonly shadowGateOverlayBarClass = computed(() => {
        return this.shadowLearningDone() ? 'bg-slate-200' : 'bg-amber-400/90';
    });

    readonly shadowingRequiredCount = computed(() => this.shadowStatus()?.required_shadowing_outcome_count ?? 0);

    readonly shadowingReadyForShadowGate = computed(() => {
        const required = this.shadowingRequiredCount();
        if (required <= 0) {
            return true;
        }
        return (this.shadowStatus()?.resolved_outcome_count ?? 0) >= required;
    });

    readonly shadowGateOverlayProgress = computed(() => {
        if (!this.shadowingReadyForShadowGate()) {
            return 0;
        }
        return this.shadowGateEligibleProgress();
    });

    readonly shadowHoursBarClass = computed(() => {
        return this.shadowLearningDone() ? 'bg-slate-200' : 'bg-amber-400/80';
    });

    readonly shadowHoursProgress = computed(() => {
        const progress = this.shadowStatus()?.hours_progress_percentage ?? 0;
        return Math.min(progress, 100);
    });

    readonly shadowingProgressBarClass = computed(() => {
        return this.shadowLearningDone() ? 'bg-slate-200' : 'bg-amber-400/30';
    });

    readonly shadowLearningTextClass = computed(() => {
        return this.shadowLearningDone() ? 'text-slate-200' : 'text-amber-400/80';
    });

    readonly shadowProgressClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'bg-purple-400';
        }
        if (this.shadowRegimeLabel() === 'shadowing') {
            return 'bg-amber-400';
        }
        if (this.shadowRegimeLabel() === 'cortexing') {
            return 'bg-pink-400';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'bg-slate-500';
        }
        return 'bg-slate-700';
    });

    readonly shadowRegimeClasses = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'bg-purple-500/10 text-purple-300 border-purple-500/20';
        }
        if (this.shadowRegimeLabel() === 'shadowing') {
            return 'bg-amber-500/10 text-amber-300 border-amber-500/20';
        }
        if (this.shadowRegimeLabel() === 'cortexing') {
            return 'bg-pink-500/10 text-pink-300 border-pink-500/20';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'bg-slate-500/10 text-slate-300 border-slate-500/20';
        }
        return 'bg-slate-500/10 text-slate-300 border-slate-500/20';
    });

    readonly shadowSparseExpectedValueUsd = computed<number | null>(() => {
        if (!this.shadowMetricsReady()) {
            return null;
        }
        return this.mapNullable(this.shadowRegime(), (shadowRegime) => shadowRegime.sparse_expected_value_usd);
    });

    readonly shadowSparseExpectedValueUsdThreshold = computed<number | null>(() =>
        this.mapNullable(this.shadowRegime(), (shadowRegime) => shadowRegime.sparse_expected_value_usd_threshold)
    );

    readonly shadowSparseExpectedValueProgress = computed(() => {
        if (!this.shadowRegimeGateEnabled()) {
            return 100;
        }
        const threshold = this.shadowSparseExpectedValueUsdThreshold();
        const value = this.shadowSparseExpectedValueUsd();
        if (threshold === null || value === null) {
            return null;
        }
        if (value >= threshold) {
            return 100;
        }
        const worstValue: number = -30.0;
        const progress: number = Math.min(100, Math.max(0, (value / worstValue) * 100));
        return progress;
    });

    readonly shadowSparseExpectedValueBarClass = computed(() => {
        const progress = this.shadowSparseExpectedValueProgress();
        if (progress === null) {
            return 'bg-slate-700';
        }
        if (this.shadowLearningDone()) {
            return 'bg-slate-200';
        }
        return progress >= 100 ? 'bg-purple-400' : 'bg-red-400';
    });

    readonly shadowSparseExpectedValueClass = computed(() => {
        const progress = this.shadowSparseExpectedValueProgress();
        if (progress === null) {
            return 'text-slate-200';
        }
        if (this.shadowLearningDone()) {
            return 'text-slate-100';
        }
        return progress >= 100 ? 'text-purple-400' : 'text-red-400';
    });

    readonly shadowSparseExpectedValueFloorLabel = computed(() => {
        if (!this.shadowRegimeGateEnabled()) {
            return '-∞';
        }
        return this.formatUsdValue(this.shadowSparseExpectedValueUsdThreshold());
    });

    readonly shadowSparseExpectedValueGeometryLabel = computed(() => {
        const regime = this.shadowRegime();
        if (!regime) {
            return '—';
        }
        return `sparse ev sma · ${this.formatShadowMetricLookbackDays(regime.sparse_expected_value_lookback_days)}d · ${regime.sparse_expected_value_bucket_width_seconds}s · ${regime.sparse_expected_value_moving_average_period} samples`;
    });

    readonly shadowSparseExpectedValueGeometryTooltip = computed(() => {
        const regime = this.shadowRegime();
        if (!regime) {
            return '';
        }
        const lookback = this.formatShadowMetricLookbackDays(regime.sparse_expected_value_lookback_days);
        const bucket = regime.sparse_expected_value_bucket_width_seconds;
        const period = regime.sparse_expected_value_moving_average_period;
        const sampleWindow = this.formatSampleWindowDuration(period, bucket);
        return `Tracks the <span class="text-purple-200 font-black uppercase tracking-widest text-[9px] mx-1">estimated value regime</span>: average dollars won or lost per resolved verdict, smoothed over <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${period}</span> non-empty verdict buckets of <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${bucket}s</span> each (about <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${sampleWindow}</span> of samples), inside a rolling <span class="inline-flex rounded bg-white/10 px-1 text-white font-black">${lookback}-day</span> history.`;
    });

    readonly shadowTitleTextClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'text-purple-300';
        }
        if (this.shadowRegimeLabel() === 'shadowing') {
            return 'text-amber-300';
        }
        if (this.shadowRegimeLabel() === 'cortexing') {
            return 'text-pink-300';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'text-slate-300';
        }
        return 'text-slate-300';
    });

    readonly shadowTotalProgress = computed(() => {
        return Math.min(this.shadowStatus()?.shadowing_progress_percentage ?? 0, 100);
    });

    readonly shadowTotalResolvedCount = computed(() => {
        const count = this.shadowStatus()?.resolved_outcome_count ?? 0;
        return Math.min(count, this.shadowingRequiredCount());
    });

    readonly shadowTotalTooltip = computed(() => {
        return `Represents outcomes serving as the <span class="text-slate-200 font-bold uppercase tracking-widest text-[9px] mx-1">Statistical Baseline</span>; they cannot be shadowed yet as they are used to calibrate the engine before activation.`;
    });

    readonly shadowTradable = computed(() => {
        return this.shadowPhase() === 'TRADABLE';
    });

    readonly shadowWinRate = computed<number | null>(() => {
        if (!this.shadowMetricsReady()) {
            return null;
        }
        return this.mapNullable(this.shadowRegime(), (shadowRegime) => shadowRegime.win_rate_percentage);
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

    formatSampleWindowDuration(sampleCount: number, bucketSeconds: number): string {
        if (!Number.isFinite(sampleCount) || !Number.isFinite(bucketSeconds) || sampleCount <= 0 || bucketSeconds <= 0) {
            return '—';
        }
        const totalSeconds = sampleCount * bucketSeconds;
        if (totalSeconds < 3600) {
            return `${Math.round(totalSeconds / 60)} min`;
        }
        const totalHours = totalSeconds / 3600;
        if (totalHours < 24) {
            return `${totalHours.toFixed(totalHours >= 10 ? 0 : 1)} h`;
        }
        return `${(totalHours / 24).toFixed(1)} d`;
    }

    formatShadowMetricLookbackDays(days: number): string {
        if (Number.isInteger(days)) {
            return String(days);
        }
        const rounded = Math.round(days * 10) / 10;
        return rounded % 1 === 0 ? String(Math.round(rounded)) : rounded.toFixed(1);
    }

    formatUsdValue(value: number | null | undefined): string {
        if (value === null || value === undefined || !Number.isFinite(value)) {
            return '—';
        }
        return `$ ${value.toFixed(2)}`;
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
