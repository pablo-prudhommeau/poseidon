import { CommonModule } from '@angular/common';
import { Component, computed, inject, input, output } from '@angular/core';
import { Tooltip } from 'primeng/tooltip';
import { TradingShadowingPhase, TradingShadowingRegimePayload } from '../../../../core/models';
import { OptionalNumberPipe } from '../../../../core/optional-number.pipe';
import { WebSocketService } from '../../../../core/websocket.service';
import {
    computeProgressPercentage,
    deriveShadowEdgeGateSatisfied,
    formatHumanDurationFromDays,
    formatHumanDurationFromSeconds,
    formatMultiplier,
    formatShadowingMetricLookbackDays,
    formatUsdValue,
    isNonNegative,
    mapNullable
} from '../trading-overview.utils';
import { PROGRESS_TONE, ProgressTone, resolvePhasePalette } from './trading-overview-shadowing-regime.palette';
import { buildShadowingRegimeStatusTooltip } from './trading-overview-shadowing-regime-status-tooltip.builder';

@Component({
    standalone: true,
    selector: 'app-trading-overview-shadowing-regime',
    imports: [CommonModule, OptionalNumberPipe, Tooltip],
    templateUrl: './trading-overview-shadowing-regime.component.html',
    styleUrl: './trading-overview-shadowing-regime.component.css'
})
export class TradingOverviewShadowingRegimeComponent {
    readonly overrideRegime = input<TradingShadowingRegimePayload | null | undefined>(undefined);

    private readonly webSocketService = inject(WebSocketService);

    readonly shadowingRegime = computed(() => {
        const override = this.overrideRegime();
        if (override !== undefined) {
            return override;
        }
        return this.webSocketService.tradingShadowingRegime();
    });

    readonly shadowingStatus = computed(() => this.shadowingRegime());
    readonly cortexGateEnabled = computed(() => this.shadowingStatus()?.cortex_gate_enabled ?? false);
    readonly cortexTrainingRequiredCount = computed(() => this.shadowingStatus()?.cortex_training_required_outcome_count ?? 0);
    readonly shadowingRequiredCount = computed(() => this.shadowingStatus()?.required_outcome_count ?? 0);

    readonly shadowingReadyForGate = computed(() => {
        const required = this.shadowingRequiredCount();
        if (required <= 0) {
            return true;
        }
        return (this.shadowingStatus()?.resolved_outcome_count ?? 0) >= required;
    });

    readonly cortexGateEligibleProgress = computed(() => {
        if (!this.cortexGateEnabled() || !this.shadowingReadyForGate()) {
            return 0;
        }
        return computeProgressPercentage(this.shadowingStatus()?.cortex_training_eligible_outcome_count, this.cortexTrainingRequiredCount());
    });

    readonly cortexGateEligibleResolvedCount = computed(() => {
        if (!this.cortexGateEnabled() || !this.shadowingReadyForGate()) {
            return 0;
        }
        const count = this.shadowingStatus()?.cortex_training_eligible_outcome_count ?? 0;
        return Math.min(count, this.cortexTrainingRequiredCount());
    });

    readonly cortexGateEligibleTooltip = computed(() => {
        return `Counts resolved non-staled probes with complete shadowing regime and shadowing metrics. Cortexing accumulation starts only after the <span class="text-amber-300 font-bold uppercase tracking-widest text-[9px] mx-1">shadowing gate-ready threshold</span> is reached.`;
    });

    readonly cortexTrainingReady = computed(() => {
        if (!this.cortexGateEnabled()) {
            return false;
        }
        const required = this.cortexTrainingRequiredCount();
        if (required <= 0) {
            return true;
        }
        return (this.shadowingStatus()?.cortex_training_eligible_outcome_count ?? 0) >= required;
    });

    readonly shadowingPhase = computed<TradingShadowingPhase | null>(() => this.shadowingRegime()?.phase ?? null);

    readonly cortexingTone = computed<ProgressTone>(() => {
        if (!this.shadowingReadyForGate()) {
            return 'pending';
        }
        if (this.cortexTrainingReady()) {
            return 'done';
        }
        return this.shadowingPhase() === 'CORTEXING' ? 'cortexing' : 'shadowingGate';
    });

    readonly cortexingProgressBarClass = computed(() => PROGRESS_TONE[this.cortexingTone()].bar);
    readonly cortexingProgressTextClass = computed(() => PROGRESS_TONE[this.cortexingTone()].value);

    readonly shadowingLearningProgressVisible = computed(() => {
        const phase = this.shadowingPhase();
        return phase === 'SHADOWING' || phase === 'CORTEXING';
    });

    readonly cortexingProgressVisible = computed(() => this.cortexGateEnabled() && this.shadowingLearningProgressVisible());
    readonly formatMultiplier = formatMultiplier;
    readonly fundamentalsGateEnabled = computed(() => this.shadowingRegime()?.fundamentals_gate_enabled ?? false);
    readonly openChronicle = output<void>();
    readonly phasePalette = computed(() => resolvePhasePalette(this.shadowingPhase()));
    readonly shadowingCardBorderClass = computed<string>(() => this.phasePalette().cardBorder);

    readonly shadowingChronicleGeometryLabel = computed(() => {
        const regime = this.shadowingRegime();
        if (!regime) {
            return '—';
        }
        const lookbackDays = regime.edge_chronicle_profit_factor_lookback_days;
        const bucketWidthSeconds = regime.edge_chronicle_profit_factor_bucket_width_seconds;
        const movingAveragePeriod = regime.edge_chronicle_profit_factor_moving_average_period;
        if (
            lookbackDays === null ||
            lookbackDays === undefined ||
            bucketWidthSeconds === null ||
            bucketWidthSeconds === undefined ||
            movingAveragePeriod === null ||
            movingAveragePeriod === undefined
        ) {
            return '—';
        }
        const lookbackLabel = formatShadowingMetricLookbackDays(lookbackDays);
        return `pf · <span class="text-slate-400">${lookbackLabel}</span>d · <span class="text-slate-400">${bucketWidthSeconds}</span>sec · <span class="text-slate-400">${movingAveragePeriod}</span>smp`;
    });

    readonly shadowingChronicleGeometryTooltip = computed(() => {
        const regime = this.shadowingRegime();
        if (!regime) {
            return '';
        }
        const lookbackDays = regime.edge_chronicle_profit_factor_lookback_days;
        const bucket = regime.edge_chronicle_profit_factor_bucket_width_seconds;
        const period = regime.edge_chronicle_profit_factor_moving_average_period;
        if (lookbackDays === null || lookbackDays === undefined || bucket === null || bucket === undefined || period === null || period === undefined) {
            return '';
        }
        const emphasize = (value: string): string => `<span class="font-semibold text-slate-100">${value}</span>`;
        const windowDuration = formatHumanDurationFromSeconds(bucket);
        const coverage = formatHumanDurationFromSeconds(period * bucket);
        const history = formatHumanDurationFromDays(lookbackDays);
        return (
            `<p class="mb-2"><span class="text-purple-200 font-black uppercase tracking-[0.16em] text-[9px]">profit factor</span></p>` +
            `<p class="mb-2">For every dollar lost on resolved verdicts, how many dollars are won. ${emphasize('Above 1.00')} means the strategy is net profitable — the higher it climbs, the stronger the edge.</p>` +
            `<p>It is a moving average over the latest ${emphasize(String(period))} ${windowDuration}-long windows that actually contain verdicts (${emphasize(coverage)} of activity), and only looks back over the last ${emphasize(history)}.</p>`
        );
    });

    readonly shadowingMetricsReady = computed(() => {
        const phase: TradingShadowingPhase | null = this.shadowingPhase();
        return phase === 'TRADABLE' || phase === 'BEAR';
    });

    readonly shadowingChronicleProfitFactor = computed<number | null>(() => {
        if (!this.shadowingMetricsReady()) {
            return null;
        }
        return mapNullable(this.shadowingRegime(), (shadowingRegime) => shadowingRegime.edge_chronicle_profit_factor);
    });

    readonly shadowingChronicleProfitFactorThreshold = computed<number | null>(() =>
        mapNullable(this.shadowingRegime(), (shadowingRegime) => shadowingRegime.edge_chronicle_profit_factor_threshold)
    );

    readonly shadowingEdgeGateEnabled = computed(() => this.shadowingRegime()?.edge_gate_enabled ?? false);

    readonly shadowingChronicleProfitFactorProgress = computed(() => {
        if (!this.shadowingMetricsReady()) {
            return null;
        }
        if (!this.shadowingEdgeGateEnabled()) {
            return 100;
        }
        const threshold = this.shadowingChronicleProfitFactorThreshold();
        const value = this.shadowingChronicleProfitFactor();
        if (threshold === null || value === null) {
            return null;
        }
        if (value >= threshold) {
            return 100;
        }
        if (threshold <= 0) {
            return 0;
        }
        return Math.min(100, (value / threshold) * 100);
    });

    readonly shadowingLearningDone = computed(() => {
        return this.shadowingLearningProgressVisible() && this.shadowingMetricsReady();
    });

    readonly shadowingChronicleProfitFactorBarClass = computed(() => {
        const progress = this.shadowingChronicleProfitFactorProgress();
        if (progress === null || !this.shadowingEdgeGateEnabled() || this.shadowingLearningDone()) {
            return PROGRESS_TONE.done.bar;
        }
        return progress >= 100 ? 'bg-purple-400' : 'bg-red-400';
    });

    readonly shadowingChronicleProfitFactorFloorLabel = computed(() => {
        if (!this.shadowingEdgeGateEnabled()) {
            return '-∞';
        }
        const threshold = this.shadowingChronicleProfitFactorThreshold();
        return threshold === null ? '—' : threshold.toFixed(2);
    });

    readonly shadowingChronicleProfitFactorValueClass = computed(() => {
        const progress = this.shadowingChronicleProfitFactorProgress();
        if (progress === null || !this.shadowingEdgeGateEnabled() || this.shadowingLearningDone()) {
            return 'text-white';
        }
        return progress >= 100 ? 'text-purple-400' : 'text-red-400';
    });

    readonly shadowingEdgeGateSatisfied = computed<boolean>(() => {
        const regime = this.shadowingRegime();
        if (!regime?.edge_gate_enabled) {
            return false;
        }
        return deriveShadowEdgeGateSatisfied(
            regime.edge_chronicle_profit_factor,
            regime.edge_chronicle_profit_factor_threshold,
            regime.edge_sparse_expected_value_usd,
            regime.edge_sparse_expected_value_usd_threshold
        );
    });

    readonly shadowingRequiredHours = computed(() => this.shadowingStatus()?.required_hours ?? 0);

    readonly shadowingElapsedHours = computed(() => {
        const elapsed = this.shadowingStatus()?.elapsed_hours ?? 0;
        return Math.min(elapsed, this.shadowingRequiredHours());
    });

    readonly shadowingExpectedPnlVelocity = computed<number | null>(() => {
        if (!this.shadowingMetricsReady()) {
            return null;
        }
        return mapNullable(this.shadowingRegime(), (shadowingRegime) => shadowingRegime.metrics_meta_expected_pnl_velocity);
    });

    readonly shadowingExpectedValue = computed<number | null>(() => {
        if (!this.shadowingMetricsReady()) {
            return null;
        }
        return mapNullable(this.shadowingRegime(), (shadowingRegime) => shadowingRegime.metrics_meta_expected_value_usd);
    });

    readonly shadowingGateRequiredCount = computed(() => this.shadowingStatus()?.edge_required_outcome_count ?? 0);

    readonly shadowingGateEligibleProgress = computed(() => {
        return computeProgressPercentage(this.shadowingStatus()?.edge_eligible_outcome_count, this.shadowingGateRequiredCount());
    });

    readonly shadowingGateEligibleResolvedCount = computed(() => {
        if (!this.shadowingReadyForGate()) {
            return 0;
        }
        const count = this.shadowingStatus()?.edge_eligible_outcome_count ?? 0;
        return Math.min(count, this.shadowingGateRequiredCount());
    });

    readonly shadowingGateEligibleTooltip = computed(() => {
        return `Counts resolved probes with complete <span class="text-amber-300 font-bold uppercase tracking-widest text-[9px] mx-1">shadowing regime + shadowing metrics</span>. These are eligible to unlock the shadowing gate.`;
    });

    readonly shadowingGateReadyForCortex = computed(() => {
        const required = this.shadowingGateRequiredCount();
        if (required <= 0) {
            return true;
        }
        return (this.shadowingStatus()?.edge_eligible_outcome_count ?? 0) >= required;
    });

    readonly shadowingGateTone = computed<ProgressTone>(() => {
        if (!this.shadowingReadyForGate()) {
            return 'pending';
        }
        if (this.shadowingGateReadyForCortex()) {
            return 'done';
        }
        return 'shadowingGate';
    });

    readonly shadowingGateProgressValueClass = computed(() => PROGRESS_TONE[this.shadowingGateTone()].value);
    readonly shadowingGateReadyOverlayBarClass = computed(() => PROGRESS_TONE[this.shadowingGateTone()].bar);

    readonly shadowingGateReadyOverlayProgress = computed(() => {
        if (!this.shadowingReadyForGate()) {
            return 0;
        }
        return this.shadowingGateEligibleProgress();
    });

    readonly shadowingHoursReady = computed(() => {
        const required = this.shadowingRequiredHours();
        if (required <= 0) {
            return true;
        }
        return (this.shadowingStatus()?.elapsed_hours ?? 0) >= required;
    });

    readonly shadowingHoursTone = computed<ProgressTone>(() => {
        if (this.shadowingHoursReady()) {
            return 'done';
        }
        return this.shadowingPhase() === 'CORTEXING' ? 'cortexing' : 'shadowingGate';
    });

    readonly shadowingHoursBarClass = computed(() => PROGRESS_TONE[this.shadowingHoursTone()].bar);

    readonly shadowingHoursProgress = computed(() => {
        return computeProgressPercentage(this.shadowingStatus()?.elapsed_hours, this.shadowingRequiredHours());
    });

    readonly shadowingHoursProgressValueClass = computed(() => PROGRESS_TONE[this.shadowingHoursTone()].value);

    readonly shadowingLearningTextClass = computed(() => {
        return this.shadowingLearningDone() ? 'text-white' : 'text-slate-500';
    });

    readonly shadowingRawProgress = computed(() => {
        return computeProgressPercentage(this.shadowingStatus()?.resolved_outcome_count, this.shadowingRequiredCount());
    });

    readonly shadowingRawTone = computed<ProgressTone>(() => (this.shadowingReadyForGate() ? 'done' : 'shadowingRaw'));
    readonly shadowingRawProgressBarClass = computed(() => PROGRESS_TONE[this.shadowingRawTone()].bar);
    readonly shadowingRawProgressValueClass = computed(() => PROGRESS_TONE[this.shadowingRawTone()].value);
    readonly shadowingRegimeClasses = computed(() => this.phasePalette().tagClasses);
    readonly shadowingRegimeDetailsPending = computed(() => this.shadowingRegime() === null);

    readonly shadowingRegimeLabel = computed<string>(() => {
        const phase: TradingShadowingPhase | null = this.shadowingPhase();
        if (phase === null) {
            return '—';
        }
        return phase.toLowerCase();
    });

    readonly toxicMetricsGateEnabled = computed(() => this.shadowingRegime()?.toxic_metrics_gate_enabled ?? false);

    readonly shadowingRegimeStatusTooltip = computed<string>(() =>
        buildShadowingRegimeStatusTooltip({
            phase: this.shadowingPhase(),
            detailsPending: this.shadowingRegimeDetailsPending(),
            training: {
                resolvedCount: this.shadowingStatus()?.resolved_outcome_count ?? 0,
                requiredCount: this.shadowingRequiredCount(),
                gateEligibleCount: this.shadowingStatus()?.edge_eligible_outcome_count ?? 0,
                gateRequiredCount: this.shadowingGateRequiredCount(),
                cortexEligibleCount: this.shadowingStatus()?.cortex_training_eligible_outcome_count ?? 0,
                cortexRequiredCount: this.cortexTrainingRequiredCount(),
                elapsedHours: this.shadowingStatus()?.elapsed_hours ?? 0,
                requiredHours: this.shadowingRequiredHours(),
                cortexGateEnabled: this.cortexGateEnabled()
            },
            gates: {
                edgeGateEnabled: this.shadowingEdgeGateEnabled(),
                edgeGateSatisfied: this.shadowingEdgeGateSatisfied(),
                cortexGateEnabled: this.cortexGateEnabled(),
                fundamentalsGateEnabled: this.fundamentalsGateEnabled(),
                toxicMetricsGateEnabled: this.toxicMetricsGateEnabled()
            }
        })
    );

    readonly shadowingSparseExpectedValueUsd = computed<number | null>(() => {
        if (!this.shadowingMetricsReady()) {
            return null;
        }
        return mapNullable(this.shadowingRegime(), (shadowingRegime) => shadowingRegime.edge_sparse_expected_value_usd);
    });

    readonly shadowingSparseExpectedValueUsdThreshold = computed<number | null>(() =>
        mapNullable(this.shadowingRegime(), (shadowingRegime) => shadowingRegime.edge_sparse_expected_value_usd_threshold)
    );

    readonly shadowingSparseExpectedValueProgress = computed(() => {
        if (!this.shadowingMetricsReady()) {
            return null;
        }
        if (!this.shadowingEdgeGateEnabled()) {
            return 100;
        }
        const threshold = this.shadowingSparseExpectedValueUsdThreshold();
        const value = this.shadowingSparseExpectedValueUsd();
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

    readonly shadowingSparseExpectedValueBarClass = computed(() => {
        const progress = this.shadowingSparseExpectedValueProgress();
        if (progress === null || !this.shadowingEdgeGateEnabled() || this.shadowingLearningDone()) {
            return PROGRESS_TONE.done.bar;
        }
        return progress >= 100 ? 'bg-purple-400' : 'bg-red-400';
    });

    readonly shadowingSparseExpectedValueClass = computed(() => {
        const progress = this.shadowingSparseExpectedValueProgress();
        if (progress === null || !this.shadowingEdgeGateEnabled() || this.shadowingLearningDone()) {
            return 'text-white';
        }
        return progress >= 100 ? 'text-purple-400' : 'text-red-400';
    });

    readonly shadowingSparseExpectedValueFloorLabel = computed(() => {
        if (!this.shadowingEdgeGateEnabled()) {
            return '-∞';
        }
        return formatUsdValue(this.shadowingSparseExpectedValueUsdThreshold());
    });

    readonly shadowingSparseExpectedValueGeometryLabel = computed(() => {
        const regime = this.shadowingRegime();
        if (!regime) {
            return '—';
        }
        const lookbackDays = regime.edge_sparse_expected_value_lookback_days;
        const bucketWidthSeconds = regime.edge_sparse_expected_value_bucket_width_seconds;
        const movingAveragePeriod = regime.edge_sparse_expected_value_moving_average_period;
        if (
            lookbackDays === null ||
            lookbackDays === undefined ||
            bucketWidthSeconds === null ||
            bucketWidthSeconds === undefined ||
            movingAveragePeriod === null ||
            movingAveragePeriod === undefined
        ) {
            return '—';
        }
        const lookbackLabel = formatShadowingMetricLookbackDays(lookbackDays);
        return `ev · <span class="text-slate-400">${lookbackLabel}</span>d · <span class="text-slate-400">${bucketWidthSeconds}</span>sec · <span class="text-slate-400">${movingAveragePeriod}</span>smp`;
    });

    readonly shadowingSparseExpectedValueGeometryTooltip = computed(() => {
        const regime = this.shadowingRegime();
        if (!regime) {
            return '';
        }
        const lookbackDays = regime.edge_sparse_expected_value_lookback_days;
        const bucket = regime.edge_sparse_expected_value_bucket_width_seconds;
        const period = regime.edge_sparse_expected_value_moving_average_period;
        if (lookbackDays === null || lookbackDays === undefined || bucket === null || bucket === undefined || period === null || period === undefined) {
            return '';
        }
        const emphasize = (value: string): string => `<span class="font-semibold text-slate-100">${value}</span>`;
        const windowDuration = formatHumanDurationFromSeconds(bucket);
        const coverage = formatHumanDurationFromSeconds(period * bucket);
        const history = formatHumanDurationFromDays(lookbackDays);
        return (
            `<p class="mb-2"><span class="text-purple-200 font-black uppercase tracking-[0.16em] text-[9px]">expected value</span></p>` +
            `<p class="mb-2">The average dollars won or lost on each resolved verdict. ${emphasize('Above zero')} means a typical trade ends in profit — the higher it climbs, the stronger the edge.</p>` +
            `<p>It is a moving average over the latest ${emphasize(String(period))} ${windowDuration}-long windows that actually contain verdicts (${emphasize(coverage)} of activity), and only looks back over the last ${emphasize(history)}.</p>`
        );
    });

    readonly shadowingTitleTextClass = computed(() => this.phasePalette().titleText);

    readonly shadowingTotalResolvedCount = computed(() => {
        const count = this.shadowingStatus()?.resolved_outcome_count ?? 0;
        return Math.min(count, this.shadowingRequiredCount());
    });

    readonly shadowingTotalTooltip = computed(() => {
        return `Counts all resolved probes used to unlock the first <span class="text-amber-300 font-bold uppercase tracking-widest text-[9px] mx-1">shadowing baseline</span>. Shadowing metrics only become effective after this baseline is available.`;
    });

    readonly shadowingWinRate = computed<number | null>(() => {
        if (!this.shadowingMetricsReady()) {
            return null;
        }
        return mapNullable(this.shadowingRegime(), (shadowingRegime) =>
            shadowingRegime.metrics_meta_win_rate === null || shadowingRegime.metrics_meta_win_rate === undefined
                ? null
                : shadowingRegime.metrics_meta_win_rate * 100
        );
    });

    readonly showChronicleButton = input(true);
}
