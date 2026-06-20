import { PositionPhase } from '../../core/models';

export function resolvePositionPhasePillClass(phase: PositionPhase | string | null | undefined, options?: { closingPreviewClass?: string }): string {
    switch (phase) {
        case 'OPEN':
            return 'poseidon-grid-pill--info';
        case 'PARTIAL':
            return 'poseidon-grid-pill--warn';
        case 'CLOSING':
            return options?.closingPreviewClass ?? 'poseidon-grid-pill--closing-negative';
        case 'CLOSED':
            return 'poseidon-grid-pill--closed';
        case 'STALED':
            return 'poseidon-grid-pill--neutral';
        default:
            return '';
    }
}

export function resolvePositionPhaseIconClass(phase: PositionPhase | string | null | undefined): string {
    switch (phase) {
        case 'OPEN':
            return 'fa-circle-dot';
        case 'PARTIAL':
            return 'fa-circle-half-stroke';
        case 'CLOSING':
            return 'fa-hourglass-half';
        case 'CLOSED':
            return 'fa-circle-check';
        case 'STALED':
            return 'fa-triangle-exclamation';
        default:
            return 'fa-circle';
    }
}

export function resolveTradeSideIconClass(tradeSide: string | null | undefined): string {
    return tradeSide === 'BUY' ? 'fa-arrow-down-long' : 'fa-arrow-up-long';
}

export function positionPhasePillNgClasses(
    phase: PositionPhase | string | null | undefined,
    options?: { closingPreviewClass?: string }
): Record<string, boolean> {
    const classes: Record<string, boolean> = {
        'poseidon-grid-pill--info': phase === 'OPEN',
        'poseidon-grid-pill--warn': phase === 'PARTIAL',
        'poseidon-grid-pill--closed': phase === 'CLOSED',
        'poseidon-grid-pill--neutral': phase === 'STALED'
    };
    if (phase === 'CLOSING' && options?.closingPreviewClass) {
        classes[options.closingPreviewClass] = true;
    }
    return classes;
}
