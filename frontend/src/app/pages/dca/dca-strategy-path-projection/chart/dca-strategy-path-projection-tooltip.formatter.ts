import type { DcaStrategyPathAdjustTooltipPositionHost, DcaStrategyPathTooltipSeriesInfoLike } from '../data/dca-strategy-path-projection.models';
import {
    dcaStrategyPathLegendHidesTooltipHit,
    dcaStrategyPathLegendSwatchKind,
    dcaStrategyPathSeriesDisplayLabel,
    dcaStrategyPathSeriesUsesDashedLegendSwatch,
    type DcaStrategyPathLegendSwatchKind
} from '../data/dca-strategy-path-projection-legend.utils';
import {
    DCA_STRATEGY_PATH_METRIC_COLORS,
    DCA_STRATEGY_PATH_TOOLTIP_COMPACT_LABEL,
    DCA_STRATEGY_PATH_TOOLTIP_PREFERRED_ORDER
} from '../data/dca-strategy-path-projection-metrics.catalog';
import { DCA_STRATEGY_PATH_SERIES } from '../data/dca-strategy-path-projection-series-names';

function escapeSvgText(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

export function dcaStrategyPathTooltipLabel(seriesName: string): string {
    return DCA_STRATEGY_PATH_TOOLTIP_COMPACT_LABEL[seriesName] ?? dcaStrategyPathSeriesDisplayLabel(seriesName);
}

export function dcaStrategyPathTooltipSwatchKind(seriesName: string): DcaStrategyPathLegendSwatchKind {
    return dcaStrategyPathLegendSwatchKind(seriesName);
}

function resolveTooltipBandSwatchColors(seriesName: string): { bandFillAbove: string; bandFillBelow: string } {
    if (seriesName === DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand) {
        return {
            bandFillAbove: DCA_STRATEGY_PATH_METRIC_COLORS.pruBandLegendWhenEffectiveAbove,
            bandFillBelow: DCA_STRATEGY_PATH_METRIC_COLORS.pruBandLegendWhenProjectedAbove
        };
    }
    return {
        bandFillAbove: DCA_STRATEGY_PATH_METRIC_COLORS.marketBandLegendWhenEffectiveAbove,
        bandFillBelow: DCA_STRATEGY_PATH_METRIC_COLORS.marketBandLegendWhenProjectedAbove
    };
}

export function buildDcaStrategyPathCursorTooltipSvg(
    sci: DcaStrategyPathAdjustTooltipPositionHost,
    seriesInfos: DcaStrategyPathTooltipSeriesInfoLike[],
    svgAnnotation: unknown
): string {
    const hits = seriesInfos
        .filter((entry) => entry.isHit)
        .filter((entry) => (entry.seriesName ?? '').trim().length > 0)
        .filter((entry) => !dcaStrategyPathLegendHidesTooltipHit((entry.seriesName ?? '').trim()));
    if (hits.length === 0) {
        return '<svg width="1" height="1" xmlns="http://www.w3.org/2000/svg"></svg>';
    }

    const byName = new Map<string, (typeof hits)[number]>();
    for (const hit of hits) {
        byName.set((hit.seriesName ?? '').trim(), hit);
    }
    const ordered: (typeof hits)[number][] = [];
    for (const name of DCA_STRATEGY_PATH_TOOLTIP_PREFERRED_ORDER) {
        const match = byName.get(name);
        if (match) {
            ordered.push(match);
            byName.delete(name);
        }
    }
    for (const leftover of byName.values()) {
        ordered.push(leftover);
    }

    const rows = ordered.slice(0, DCA_STRATEGY_PATH_TOOLTIP_PREFERRED_ORDER.length).map((entry) => {
        const seriesName = (entry.seriesName ?? '').trim();
        const label = dcaStrategyPathTooltipLabel(seriesName);
        const text = (entry.formattedYValue ?? '').trim();
        const stroke = entry.stroke ?? DCA_STRATEGY_PATH_METRIC_COLORS.tooltipFallbackStroke;
        const dashed = dcaStrategyPathSeriesUsesDashedLegendSwatch(seriesName, entry.renderableSeries?.strokeDashArray);
        const bandSwatchColors = resolveTooltipBandSwatchColors(seriesName);
        return {
            label: escapeSvgText(label),
            text: escapeSvgText(text),
            stroke,
            dashed,
            kind: dcaStrategyPathTooltipSwatchKind(seriesName),
            bandFillAbove: bandSwatchColors.bandFillAbove,
            bandFillBelow: bandSwatchColors.bandFillBelow
        };
    });

    const lineHeight = 17;
    const paddingTop = 20;
    const paddingBottom = 5;
    const width = 280;
    const height = paddingTop + 16 + rows.length * lineHeight + paddingBottom;
    sci.adjustTooltipPosition?.(width, height, svgAnnotation);

    const timeLabel = escapeSvgText(`Time: ${hits[0]?.formattedXValue ?? ''}`);
    const swatchSvg = rows
        .map((row, index) => {
            const y = paddingTop + 22 + index * lineHeight;
            const x = 12;
            if (row.kind === 'area') {
                return `<rect x="${x}" y="${y - 8}" width="12" height="8" rx="1.5" fill="${row.stroke}" fill-opacity="0.35" stroke="${row.stroke}" stroke-width="1"/>`;
            }
            if (row.kind === 'band') {
                return `<rect x="${x}" y="${y - 8}" width="12" height="8" rx="1.5" fill="${row.bandFillAbove}" fill-opacity="0.45"/><rect x="${x}" y="${y - 4}" width="12" height="4" rx="0 0 1.5 1.5" fill="${row.bandFillBelow}" fill-opacity="0.45"/>`;
            }
            const dash = row.kind === 'dashed-line' || row.dashed ? '4,3' : '0';
            return `<line x1="${x}" y1="${y - 4}" x2="${x + 12}" y2="${y - 4}" stroke="${row.stroke}" stroke-width="2" stroke-dasharray="${dash}"/>`;
        })
        .join('');

    const textSvg = rows
        .map((row, index) => {
            const y = paddingTop + 22 + index * lineHeight;
            return `<text x="30" y="${y}" font-size="11" fill="${DCA_STRATEGY_PATH_METRIC_COLORS.tooltipTextPrimary}">${row.label}: ${row.text}</text>`;
        })
        .join('');

    return `
<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <linearGradient id="dcaTooltipGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${DCA_STRATEGY_PATH_METRIC_COLORS.tooltipGradientTop}" stop-opacity="0.95"/>
            <stop offset="100%" stop-color="${DCA_STRATEGY_PATH_METRIC_COLORS.tooltipGradientBottom}" stop-opacity="0.9"/>
        </linearGradient>
    </defs>
    <rect x="0.5" y="0.5" width="${width - 1}" height="${height - 1}" rx="8" fill="url(#dcaTooltipGrad)" stroke="${DCA_STRATEGY_PATH_METRIC_COLORS.tooltipBorder}" stroke-width="1"/>
    <text x="12" y="${paddingTop + 2}" font-size="11" font-weight="700" fill="${DCA_STRATEGY_PATH_METRIC_COLORS.tooltipTitle}">${timeLabel}</text>
    ${swatchSvg}
    ${textSvg}
</svg>`;
}
