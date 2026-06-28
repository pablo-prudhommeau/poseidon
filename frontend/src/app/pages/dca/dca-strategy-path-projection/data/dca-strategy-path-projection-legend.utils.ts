export type DcaStrategyPathLegendSwatchKind = 'line' | 'dashed-line' | 'area' | 'band';

const DCA_LEGEND_TYPE_SEPARATOR = ' · ';

export function dcaStrategyPathSeriesDisplayLabel(seriesName: string): string {
    if (!seriesName.includes(DCA_LEGEND_TYPE_SEPARATOR)) {
        return seriesName;
    }
    return seriesName.slice(0, seriesName.lastIndexOf(DCA_LEGEND_TYPE_SEPARATOR));
}

export function dcaStrategyPathLegendSwatchKind(seriesName: string): DcaStrategyPathLegendSwatchKind {
    const typeSuffix = seriesName.includes(DCA_LEGEND_TYPE_SEPARATOR) ? (seriesName.split(DCA_LEGEND_TYPE_SEPARATOR).pop()?.toLowerCase() ?? '') : '';
    switch (typeSuffix) {
        case 'band':
            return 'band';
        case 'dashed-line':
            return 'dashed-line';
        case 'area':
            return 'area';
        case 'line':
            return 'line';
        default:
            return 'line';
    }
}

export function dcaStrategyPathSeriesUsesDashedLegendSwatch(seriesName: string, strokeDashArray?: number[]): boolean {
    if (dcaStrategyPathLegendSwatchKind(seriesName) === 'dashed-line') {
        return true;
    }
    return Array.isArray(strokeDashArray) && strokeDashArray.length > 0;
}

export function dcaStrategyPathLegendHidesTooltipHit(seriesName: string): boolean {
    const kind = dcaStrategyPathLegendSwatchKind(seriesName);
    return kind === 'area' || kind === 'band';
}
