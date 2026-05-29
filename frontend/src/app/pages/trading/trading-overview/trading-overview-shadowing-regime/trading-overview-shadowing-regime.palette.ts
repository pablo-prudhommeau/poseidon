import { TradingShadowingPhase } from '../../../../core/models';

export interface ShadowingPhasePalette {
    titleText: string;
    cardBorder: string;
    tagClasses: string;
    glossaryBlurb: string;
    headline: string;
}

const SLATE_PHASE_PALETTE: ShadowingPhasePalette = {
    titleText: 'text-slate-300',
    cardBorder: 'border-slate-400/20 hover:border-slate-400/30',
    tagClasses: 'bg-slate-400/10 text-slate-300 border-slate-400/20',
    glossaryBlurb: 'The regime snapshot is refreshing.',
    headline: 'The regime snapshot is refreshing — check back in a moment.'
};

export const SHADOWING_PHASE_PALETTE: Record<TradingShadowingPhase, ShadowingPhasePalette> = {
    TRADABLE: {
        titleText: 'text-purple-400/80',
        cardBorder: 'border-purple-400/20 hover:border-purple-400/30',
        tagClasses: 'bg-purple-400/10 text-purple-300 border-purple-400/20',
        glossaryBlurb: 'Live trading is authorized once regime warmup completes.',
        headline: 'Regime warmup complete — live trading is authorized.'
    },
    BEAR: {
        titleText: 'text-red-400/80',
        cardBorder: 'border-red-400/20 hover:border-red-400/30',
        tagClasses: 'bg-red-400/10 text-red-300 border-red-400/20',
        glossaryBlurb: 'Edge weather dropped below its floors — trading stays paused until recovery.',
        headline: 'Edge weather slipped below its floors — trading is paused until recovery.'
    },
    SHADOWING: {
        titleText: 'text-amber-400/80',
        cardBorder: 'border-amber-400/20 hover:border-amber-400/30',
        tagClasses: 'bg-amber-400/10 text-amber-300 border-amber-400/20',
        glossaryBlurb: 'Building the first baseline of resolved outcomes.',
        headline: 'Warmup in progress — building the first baseline of resolved outcomes.'
    },
    CORTEXING: {
        titleText: 'text-pink-400/80',
        cardBorder: 'border-pink-400/20 hover:border-pink-400/30',
        tagClasses: 'bg-pink-400/10 text-pink-300 border-pink-400/20',
        glossaryBlurb: 'Gathering outcomes to train the cortex model.',
        headline: 'Warmup in progress — gathering outcomes to train the cortex model.'
    },
    SYNCING: SLATE_PHASE_PALETTE,
    DISABLED: {
        ...SLATE_PHASE_PALETTE,
        glossaryBlurb: 'All trading gates are off — the regime does not filter live trading.',
        headline: 'All trading gates are off — the regime does not filter live trading.'
    }
};

export const DEFAULT_PHASE_PALETTE: ShadowingPhasePalette = SLATE_PHASE_PALETTE;

export function resolvePhasePalette(phase: TradingShadowingPhase | null | undefined): ShadowingPhasePalette {
    if (phase === null || phase === undefined) {
        return DEFAULT_PHASE_PALETTE;
    }
    return SHADOWING_PHASE_PALETTE[phase];
}

export const SHADOWING_PHASE_ORDER: TradingShadowingPhase[] = ['TRADABLE', 'BEAR', 'CORTEXING', 'SHADOWING', 'SYNCING', 'DISABLED'];

export type ProgressTone = 'pending' | 'done' | 'shadowingRaw' | 'shadowingGate' | 'cortexing';

export interface ProgressToneClasses {
    bar: string;
    value: string;
}

export const PROGRESS_TONE: Record<ProgressTone, ProgressToneClasses> = {
    pending: { bar: 'bg-transparent', value: 'text-slate-500' },
    done: { bar: 'bg-white', value: 'text-white' },
    shadowingRaw: { bar: 'bg-amber-400/30', value: 'text-amber-200/40' },
    shadowingGate: { bar: 'bg-amber-400/90', value: 'text-amber-300' },
    cortexing: { bar: 'bg-pink-400/80', value: 'text-pink-300' }
};
