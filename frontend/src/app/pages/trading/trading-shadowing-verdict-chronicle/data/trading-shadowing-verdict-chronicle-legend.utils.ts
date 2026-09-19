export type ChronicleLegendSwatchKind = 'line' | 'dashed-line' | 'area' | 'column' | 'bubble' | 'band' | 'threshold' | 'marker' | 'path';

const CHRONICLE_LEGEND_TYPE_SEPARATOR = ' · ';

export function chronicleSeriesDisplayLabel(seriesName: string): string {
    if (!seriesName.includes(CHRONICLE_LEGEND_TYPE_SEPARATOR)) {
        return seriesName;
    }
    return seriesName.slice(0, seriesName.lastIndexOf(CHRONICLE_LEGEND_TYPE_SEPARATOR));
}

export function chronicleLegendSwatchKind(seriesName: string): ChronicleLegendSwatchKind {
    const typeSuffix = seriesName.includes(CHRONICLE_LEGEND_TYPE_SEPARATOR)
        ? (seriesName.split(CHRONICLE_LEGEND_TYPE_SEPARATOR).pop()?.toLowerCase() ?? '')
        : '';
    switch (typeSuffix) {
        case 'threshold':
            return 'threshold';
        case 'marker':
            return 'marker';
        case 'band':
            return 'band';
        case 'dashed-line':
            return 'dashed-line';
        case 'area':
            return 'area';
        case 'column':
        case 'columns':
            return 'column';
        case 'bubble':
            return 'bubble';
        case 'path':
            return 'path';
        case 'line':
            return 'line';
        default: {
            const normalized = seriesName.toLowerCase();
            if (normalized.includes('band')) {
                return 'band';
            }
            if (normalized.includes('columns')) {
                return 'column';
            }
            if (normalized.includes('area')) {
                return 'area';
            }
            if (normalized.includes('bubble')) {
                return 'bubble';
            }
            if (normalized.includes('path')) {
                return 'path';
            }
            return 'line';
        }
    }
}

export function chronicleSeriesUsesDashedLegendSwatch(seriesName: string, strokeDashArray?: number[]): boolean {
    if (chronicleLegendSwatchKind(seriesName) === 'dashed-line') {
        return true;
    }
    return Array.isArray(strokeDashArray) && strokeDashArray.length > 0;
}

export function chronicleLegendHidesTooltipHit(seriesName: string): boolean {
    const kind = chronicleLegendSwatchKind(seriesName);
    return kind === 'area' || kind === 'band' || kind === 'threshold' || kind === 'bubble' || kind === 'path';
}
