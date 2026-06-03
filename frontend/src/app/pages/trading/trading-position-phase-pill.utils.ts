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
