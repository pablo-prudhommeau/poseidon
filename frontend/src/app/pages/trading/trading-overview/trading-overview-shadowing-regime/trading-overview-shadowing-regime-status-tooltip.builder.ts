import { TradingShadowingPhase } from '../../../../core/models';
import { resolvePhasePalette, SHADOWING_PHASE_ORDER, ShadowingPhasePalette } from './trading-overview-shadowing-regime.palette';

export interface ShadowingRegimeTrainingContext {
    resolvedCount: number;
    requiredCount: number;
    gateEligibleCount: number;
    gateRequiredCount: number;
    cortexEligibleCount: number;
    cortexRequiredCount: number;
    elapsedHours: number;
    requiredHours: number;
    cortexGateEnabled: boolean;
}

export interface ShadowingRegimeGatesContext {
    edgeGateEnabled: boolean;
    edgeGateSatisfied: boolean;
    cortexGateEnabled: boolean;
    fundamentalsGateEnabled: boolean;
    toxicMetricsGateEnabled: boolean;
}

export interface ShadowingRegimeStatusTooltipContext {
    phase: TradingShadowingPhase | null;
    detailsPending: boolean;
    training: ShadowingRegimeTrainingContext;
    gates: ShadowingRegimeGatesContext;
}

function buildStatusTagHtml(phase: TradingShadowingPhase, palette: ShadowingPhasePalette): string {
    const label: string = phase.toLowerCase();
    return `<span class="${palette.tagClasses} border" style="display:inline-block;padding:4px 8px;border-radius:8px;font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:0.1em;">${label}</span>`;
}

function buildPendingHeadlineHtml(): string {
    return (
        `<p class="mb-1 text-slate-400 font-black uppercase tracking-widest text-[10px]">—</p>` +
        `<p class="mb-3 text-slate-200">Waiting for shadowing regime data from the backend.</p>`
    );
}

function buildHeadlineHtml(phase: TradingShadowingPhase | null, gates: ShadowingRegimeGatesContext): string {
    if (phase === null) {
        return `<p class="mb-3 text-slate-200">The shadowing regime status is not available yet.</p>`;
    }
    const palette: ShadowingPhasePalette = resolvePhasePalette(phase);

    let edgeSubline = '';
    if (phase === 'TRADABLE' && gates.edgeGateEnabled) {
        if (gates.edgeGateSatisfied) {
            edgeSubline = `<p class="mb-3 text-slate-400 text-[11px]">Edge weather is above its floors.</p>`;
        } else {
            edgeSubline = `<p class="mb-3 text-red-300/80 text-[11px]">Edge weather is below its floors.</p>`;
        }
    }

    return `<p class="mb-1">${buildStatusTagHtml(phase, palette)}</p>` + `<p class="mb-1 text-slate-200">${palette.headline}</p>` + edgeSubline;
}

function buildSectionSubtitleHtml(label: string): string {
    return `<p class="trading-overview-subtitle mb-1.5 leading-none">${label}</p>`;
}

function buildRowIconHtml(iconClass: string, toneClass: string): string {
    return `<span class="inline-flex w-[10px] shrink-0 items-center justify-center leading-none"><i class="fa ${iconClass} ${toneClass} text-[9px] leading-none"></i></span>`;
}

function buildTrainingThresholdRowHtml(label: string, currentCount: number, requiredCount: number, reached: boolean): string {
    const icon: string = reached ? buildRowIconHtml('fa-check', 'text-emerald-400') : buildRowIconHtml('fa-hourglass-half', 'text-slate-500');
    const valueClass: string = reached ? 'text-white' : 'text-slate-400';
    const cappedCount: number = Math.min(currentCount, requiredCount);
    return (
        `<div class="flex items-center justify-between gap-3 min-h-[14px]">` +
        `<div class="flex items-center gap-1.5">${icon}<span class="font-bold uppercase tracking-wide text-slate-300 text-[10px] leading-none">${label}</span></div>` +
        `<span class="font-bold tabular-nums text-[10px] leading-none ${valueClass}">${cappedCount}/${requiredCount}</span>` +
        `</div>`
    );
}

function buildTrainingPendingRowHtml(label: string): string {
    return (
        `<div class="flex items-center justify-between gap-3 min-h-[14px]">` +
        `<div class="flex items-center gap-1.5">${buildRowIconHtml('fa-hourglass-half', 'text-slate-500')}<span class="font-bold uppercase tracking-wide text-slate-300 text-[10px] leading-none">${label}</span></div>` +
        `<span class="font-bold tabular-nums text-[10px] leading-none text-slate-500">—/—</span>` +
        `</div>`
    );
}

function buildTrainingPendingColumnHtml(): string {
    const rows: string[] = [
        buildTrainingPendingRowHtml('raw'),
        buildTrainingPendingRowHtml('shadowing'),
        buildTrainingPendingRowHtml('cortexing'),
        buildTrainingPendingRowHtml('duration')
    ];
    return `<div class="flex-1 min-w-0 space-y-1.5">` + `${buildSectionSubtitleHtml('training')}` + `${rows.join('')}</div>`;
}

function buildGatePendingRowHtml(name: string): string {
    return (
        `<div class="flex items-center justify-between gap-3 min-h-[14px]">` +
        `<div class="flex items-center gap-1.5">${buildRowIconHtml('fa-hourglass-half', 'text-slate-500')}<span class="font-bold uppercase tracking-wide text-slate-300 text-[10px] leading-none">${name}</span></div>` +
        `<span class="text-[9px] font-bold leading-none text-slate-500">—</span>` +
        `</div>`
    );
}

function buildGatesPendingColumnHtml(): string {
    const rows: string[] = [
        buildGatePendingRowHtml('edge'),
        buildGatePendingRowHtml('cortex'),
        buildGatePendingRowHtml('fundamentals'),
        buildGatePendingRowHtml('toxic')
    ];
    return `<div class="flex-1 min-w-0 border-l border-white/10 pl-4 space-y-1.5">` + `${buildSectionSubtitleHtml('gates')}` + `${rows.join('')}</div>`;
}

function buildTrainingColumnHtml(training: ShadowingRegimeTrainingContext): string {
    const rawReached: boolean = training.resolvedCount >= training.requiredCount && training.requiredCount > 0;
    const shadowingReached: boolean = training.gateEligibleCount >= training.gateRequiredCount && training.gateRequiredCount > 0;
    const cortexReached: boolean = training.cortexEligibleCount >= training.cortexRequiredCount && training.cortexRequiredCount > 0;
    const hoursReached: boolean = training.elapsedHours >= training.requiredHours && training.requiredHours > 0;

    const hoursIcon: string = hoursReached ? buildRowIconHtml('fa-check', 'text-emerald-400') : buildRowIconHtml('fa-hourglass-half', 'text-slate-500');
    const hoursValueClass: string = hoursReached ? 'text-white' : 'text-slate-400';
    const cappedHours: number = Math.min(training.elapsedHours, training.requiredHours);
    const hoursRow: string =
        `<div class="flex items-center justify-between gap-3 min-h-[14px]">` +
        `<div class="flex items-center gap-1.5">${hoursIcon}<span class="font-bold uppercase tracking-wide text-slate-300 text-[10px] leading-none">duration</span></div>` +
        `<span class="font-bold tabular-nums text-[10px] leading-none ${hoursValueClass}">${cappedHours.toFixed(1)}h/${training.requiredHours.toFixed(1)}h</span>` +
        `</div>`;

    const rows: string[] = [];
    if (training.requiredCount > 0) {
        rows.push(buildTrainingThresholdRowHtml('raw', training.resolvedCount, training.requiredCount, rawReached));
    }
    if (training.gateRequiredCount > 0) {
        rows.push(buildTrainingThresholdRowHtml('shadowing', training.gateEligibleCount, training.gateRequiredCount, shadowingReached));
    }
    if (training.cortexGateEnabled && training.cortexRequiredCount > 0) {
        rows.push(buildTrainingThresholdRowHtml('cortexing', training.cortexEligibleCount, training.cortexRequiredCount, cortexReached));
    }
    if (training.requiredHours > 0) {
        rows.push(hoursRow);
    }
    if (rows.length === 0) {
        return '';
    }
    return `<div class="flex-1 min-w-0 space-y-1.5">` + `${buildSectionSubtitleHtml('training')}` + `${rows.join('')}</div>`;
}

function buildGateStateLabel(enabled: boolean, satisfied: boolean | null): string {
    if (!enabled) {
        return '<span class="text-[9px] font-bold uppercase tracking-wider leading-none text-slate-500">off</span>';
    }
    if (satisfied === true) {
        return '<span class="text-[9px] font-bold uppercase tracking-wider leading-none text-emerald-400">satisfied</span>';
    }
    if (satisfied === false) {
        return '<span class="text-[9px] font-bold uppercase tracking-wider leading-none text-red-400">unsatisfied</span>';
    }
    return '<span class="text-[9px] font-bold uppercase tracking-wider leading-none text-emerald-400">on</span>';
}

function buildGateRowHtml(name: string, enabled: boolean, satisfied: boolean | null): string {
    const icon: string = !enabled
        ? buildRowIconHtml('fa-circle-minus', 'text-slate-500')
        : satisfied === false
          ? buildRowIconHtml('fa-circle-xmark', 'text-red-400')
          : buildRowIconHtml('fa-circle-check', 'text-emerald-400');
    return (
        `<div class="flex items-center justify-between gap-3 min-h-[14px]">` +
        `<div class="flex items-center gap-1.5">${icon}<span class="font-bold uppercase tracking-wide text-slate-300 text-[10px] leading-none">${name}</span></div>` +
        `${buildGateStateLabel(enabled, satisfied)}` +
        `</div>`
    );
}

function buildGatesColumnHtml(gates: ShadowingRegimeGatesContext): string {
    const rows: string[] = [
        buildGateRowHtml('edge', gates.edgeGateEnabled, gates.edgeGateSatisfied),
        buildGateRowHtml('cortex', gates.cortexGateEnabled, null),
        buildGateRowHtml('fundamentals', gates.fundamentalsGateEnabled, null),
        buildGateRowHtml('toxic', gates.toxicMetricsGateEnabled, null)
    ];
    return `<div class="flex-1 min-w-0 border-l border-white/10 pl-4 space-y-1.5">` + `${buildSectionSubtitleHtml('gates')}` + `${rows.join('')}</div>`;
}

function buildTrainingAndGatesSectionHtml(detailsPending: boolean, training: ShadowingRegimeTrainingContext, gates: ShadowingRegimeGatesContext): string {
    if (detailsPending) {
        return (
            `<div class="mb-3 pt-3 border-t border-white/10 flex items-start gap-4">` +
            `${buildTrainingPendingColumnHtml()}` +
            `${buildGatesPendingColumnHtml()}</div>`
        );
    }
    const trainingColumn: string = buildTrainingColumnHtml(training);
    const gatesColumn: string = buildGatesColumnHtml(gates);
    if (!trainingColumn && !gatesColumn) {
        return '';
    }
    return (
        `<div class="mb-3 pt-3 border-t border-white/10 flex items-start gap-4">` +
        `${trainingColumn || '<div class="flex-1 min-w-0"></div>'}` +
        `${gatesColumn}</div>`
    );
}

export function buildShadowingRegimeStatusTooltip(context: ShadowingRegimeStatusTooltipContext): string {
    const headline: string = context.detailsPending ? buildPendingHeadlineHtml() : buildHeadlineHtml(context.phase, context.gates);
    const trainingAndGates: string = buildTrainingAndGatesSectionHtml(context.detailsPending, context.training, context.gates);
    const legendRows: string = SHADOWING_PHASE_ORDER.map((phase) => {
        const palette: ShadowingPhasePalette = resolvePhasePalette(phase);
        const rowOpacity: string = !context.detailsPending && phase === context.phase ? '' : 'opacity-50';
        return (
            `<div class="flex items-start gap-2 ${rowOpacity}">` +
            `${buildStatusTagHtml(phase, palette)}` +
            `<span class="text-slate-400 mt-px">${palette.glossaryBlurb}</span>` +
            `</div>`
        );
    }).join('');
    const legend: string =
        `<div class="mt-3 pt-3 border-t border-white/10 space-y-2">` + `${buildSectionSubtitleHtml('status glossary')}` + `${legendRows}</div>`;
    return headline + trainingAndGates + legend;
}
