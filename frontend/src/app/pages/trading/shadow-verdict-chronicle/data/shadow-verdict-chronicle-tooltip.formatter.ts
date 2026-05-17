import type {
    ChronicleAdjustTooltipPositionHost,
    ChronicleTooltipSeriesInfoLike,
    ChronicleVerdictBubblePointMetadata
} from './shadow-verdict-chronicle.models';
import {
    type ChronicleLegendSwatchKind,
    chronicleLegendHidesTooltipHit,
    chronicleLegendSwatchKind,
    chronicleSeriesDisplayLabel,
    chronicleSeriesUsesDashedLegendSwatch
} from './shadow-verdict-chronicle-legend.utils';
import { CHRONICLE_METRIC_COLORS, CHRONICLE_TOOLTIP_COMPACT_LABEL, CHRONICLE_TOOLTIP_PREFERRED_ORDER } from './shadow-verdict-chronicle-metrics.catalog';

export type ChronicleTooltipSwatchKind = ChronicleLegendSwatchKind;

function escapeSvgText(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function formatUsdCompact(usd: number): string {
    const absoluteUsd = Math.abs(usd);
    if (absoluteUsd >= 1_000_000) {
        return `$${(usd / 1_000_000).toFixed(2)}M`;
    }
    if (absoluteUsd >= 1_000) {
        return `$${(usd / 1_000).toFixed(1)}k`;
    }
    return `$${usd.toFixed(0)}`;
}

export function chronicleTooltipLabel(seriesName: string): string {
    return CHRONICLE_TOOLTIP_COMPACT_LABEL[seriesName] ?? chronicleSeriesDisplayLabel(seriesName);
}

export function chronicleTooltipSwatchKind(seriesName: string): ChronicleTooltipSwatchKind {
    return chronicleLegendSwatchKind(seriesName);
}

function readVerdictBubbleMetadata(entry: ChronicleTooltipSeriesInfoLike): ChronicleVerdictBubblePointMetadata | undefined {
    return entry.pointMetadata as ChronicleVerdictBubblePointMetadata | undefined;
}

function formatVerdictBubbleTooltipValue(entry: ChronicleTooltipSeriesInfoLike): string {
    const pnlText = (entry.formattedYValue ?? '').trim();
    const detailParts: string[] = [];
    const metadata = readVerdictBubbleMetadata(entry);
    const orderNotionalUsd = metadata?.orderNotionalUsd;
    if (typeof orderNotionalUsd === 'number' && Number.isFinite(orderNotionalUsd) && orderNotionalUsd > 0) {
        detailParts.push(`${formatUsdCompact(orderNotionalUsd)} notional`);
    }
    const cortexProbability = metadata?.cortexProbability;
    if (typeof cortexProbability === 'number' && Number.isFinite(cortexProbability)) {
        detailParts.push(`cortex win ${(cortexProbability * 100).toFixed(1)}%`);
    }
    if (detailParts.length === 0) {
        return pnlText;
    }
    return `${pnlText} · ${detailParts.join(' · ')}`;
}

function formatChronicleTooltipValue(seriesName: string, entry: ChronicleTooltipSeriesInfoLike): string {
    const kind = chronicleLegendSwatchKind(seriesName);
    if (kind === 'bubble') {
        return formatVerdictBubbleTooltipValue(entry);
    }
    return (entry.formattedYValue ?? '').trim();
}

export function buildChronicleCursorTooltipSvg(
    sci: ChronicleAdjustTooltipPositionHost,
    seriesInfos: ChronicleTooltipSeriesInfoLike[],
    svgAnnotation: unknown
): string {
    const hits = seriesInfos
        .filter((entry) => entry.isHit)
        .filter((entry) => (entry.seriesName ?? '').trim().length > 0)
        .filter((entry) => !chronicleLegendHidesTooltipHit((entry.seriesName ?? '').trim()));
    if (hits.length === 0) {
        return '<svg width="1" height="1" xmlns="http://www.w3.org/2000/svg"></svg>';
    }

    const byName = new Map<string, (typeof hits)[number]>();
    for (const hit of hits) {
        byName.set((hit.seriesName ?? '').trim(), hit);
    }
    const ordered: (typeof hits)[number][] = [];
    for (const name of CHRONICLE_TOOLTIP_PREFERRED_ORDER) {
        const match = byName.get(name);
        if (match) {
            ordered.push(match);
            byName.delete(name);
        }
    }
    for (const leftover of byName.values()) {
        ordered.push(leftover);
    }

    const rows = ordered.slice(0, 10).map((entry) => {
        const seriesName = (entry.seriesName ?? '').trim();
        const label = chronicleTooltipLabel(seriesName);
        const text = formatChronicleTooltipValue(seriesName, entry);
        const stroke = entry.stroke ?? CHRONICLE_METRIC_COLORS.tooltipFallbackStroke;
        const dashed = chronicleSeriesUsesDashedLegendSwatch(seriesName, entry.renderableSeries?.strokeDashArray);
        return {
            label: escapeSvgText(label),
            text: escapeSvgText(text),
            stroke,
            dashed,
            kind: chronicleTooltipSwatchKind(seriesName)
        };
    });

    const lineHeight = 17;
    const paddingTop = 20;
    const paddingBottom = 5;
    const width = 300;
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
            if (row.kind === 'column') {
                return `<rect x="${x + 1}" y="${y - 9}" width="8" height="9" rx="1.2" fill="${row.stroke}" fill-opacity="0.62" stroke="${row.stroke}" stroke-width="1"/>`;
            }
            if (row.kind === 'bubble') {
                return `<circle cx="${x + 6}" cy="${y - 4}" r="3.2" fill="${row.stroke}" fill-opacity="0.7" stroke="${row.stroke}" stroke-width="1"/>`;
            }
            if (row.kind === 'band') {
                return `<rect x="${x}" y="${y - 8}" width="12" height="8" rx="1.5" fill="${CHRONICLE_METRIC_COLORS.tooltipBandAbove}" fill-opacity="0.45"/><rect x="${x}" y="${y - 4}" width="12" height="4" rx="0 0 1.5 1.5" fill="${CHRONICLE_METRIC_COLORS.tooltipBandBelow}" fill-opacity="0.45"/>`;
            }
            const dash = row.kind === 'dashed-line' || row.dashed ? '4,3' : '0';
            return `<line x1="${x}" y1="${y - 4}" x2="${x + 12}" y2="${y - 4}" stroke="${row.stroke}" stroke-width="2" stroke-dasharray="${dash}"/>`;
        })
        .join('');

    const textSvg = rows
        .map((row, index) => {
            const y = paddingTop + 22 + index * lineHeight;
            return `<text x="30" y="${y}" font-size="11" fill="${CHRONICLE_METRIC_COLORS.tooltipTextPrimary}">${row.label}: ${row.text}</text>`;
        })
        .join('');

    return `
<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <linearGradient id="tooltipGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${CHRONICLE_METRIC_COLORS.tooltipGradientTop}" stop-opacity="0.95"/>
            <stop offset="100%" stop-color="${CHRONICLE_METRIC_COLORS.tooltipGradientBottom}" stop-opacity="0.9"/>
        </linearGradient>
    </defs>
    <rect x="0.5" y="0.5" width="${width - 1}" height="${height - 1}" rx="8" fill="url(#tooltipGrad)" stroke="${CHRONICLE_METRIC_COLORS.tooltipBorder}" stroke-width="1"/>
    <text x="12" y="${paddingTop + 2}" font-size="11" font-weight="700" fill="${CHRONICLE_METRIC_COLORS.tooltipTitle}">${timeLabel}</text>
    ${swatchSvg}
    ${textSvg}
</svg>`;
}
