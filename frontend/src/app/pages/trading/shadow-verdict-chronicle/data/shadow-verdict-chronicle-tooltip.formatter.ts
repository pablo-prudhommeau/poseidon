import type {ChronicleAdjustTooltipPositionHost, ChronicleTooltipSeriesInfoLike,} from './shadow-verdict-chronicle.models';

export type ChronicleTooltipSwatchKind = 'line' | 'area' | 'column' | 'verdict';

export const CHRONICLE_TOOLTIP_SERIES_ALIAS: Record<string, string> = {
    'Average PnL % (bucket)': 'Avg PnL %',
    'Average win rate % (bucket)': 'Avg win rate %',
    'EV per trade ($) (bucket)': 'EV / trade',
    'Profit factor (bucket)': 'Profit factor',
    'Velocity (closed / hour, bucket)': 'Velocity / h',
    'SMA average PnL %': 'SMA PnL %',
    'SMA win rate %': 'SMA win rate %',
    'SMA EV per trade': 'SMA EV / trade',
    'SMA profit factor': 'SMA profit factor',
    'SMA velocity': 'SMA velocity',
    'Non-staled verdict · win (PnL %)': 'Verdict win',
    'Non-staled verdict · loss (PnL %)': 'Verdict loss',
    'Volume · area': 'Volume area',
    'Volume · columns': 'Volume columns',
    'SMA EV per trade (area)': 'SMA EV area',
    'SMA profit factor (area)': 'SMA PF area',
};

export const CHRONICLE_TOOLTIP_PREFERRED_ORDER = [
    'Average PnL % (bucket)',
    'Average win rate % (bucket)',
    'EV per trade ($) (bucket)',
    'SMA EV per trade',
    'Profit factor (bucket)',
    'SMA profit factor',
    'Velocity (closed / hour, bucket)',
    'Volume · columns',
    'Non-staled verdict · win (PnL %)',
    'Non-staled verdict · loss (PnL %)',
] as const;

function escapeSvgText(value: string): string {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

export function chronicleTooltipAlias(seriesName: string): string {
    return CHRONICLE_TOOLTIP_SERIES_ALIAS[seriesName] ?? seriesName;
}

export function chronicleTooltipSwatchKind(seriesName: string): ChronicleTooltipSwatchKind {
    const normalized = seriesName.toLowerCase();
    if (normalized.includes('columns')) {
        return 'column';
    }
    if (normalized.includes('(area)') || normalized.includes(' area')) {
        return 'area';
    }
    if (normalized.includes('verdict')) {
        return 'verdict';
    }
    return 'line';
}

export function buildChronicleCursorTooltipSvg(
    sci: ChronicleAdjustTooltipPositionHost,
    seriesInfos: ChronicleTooltipSeriesInfoLike[],
    svgAnnotation: unknown,
): string {
    const hits = seriesInfos
        .filter(entry => entry.isHit)
        .filter(entry => (entry.seriesName ?? '').trim().length > 0)
        .filter(entry => !(entry.seriesName ?? '').includes('(area)'));
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

    const rows = ordered.slice(0, 10).map(entry => {
        const seriesName = (entry.seriesName ?? '').trim();
        const label = chronicleTooltipAlias(seriesName);
        const value = entry.formattedYValue ?? '';
        const bubble = typeof entry.zValue === 'number' && Number.isFinite(entry.zValue)
            ? ` | bubble ${entry.zValue.toFixed(1)}`
            : '';
        const stroke = entry.stroke ?? '#94a3b8';
        const isDashed = Array.isArray(entry.renderableSeries?.strokeDashArray)
            && (entry.renderableSeries?.strokeDashArray?.length ?? 0) > 0;
        return {
            label: escapeSvgText(label),
            text: escapeSvgText(`${value}${bubble}`),
            stroke,
            dashed: isDashed,
            kind: chronicleTooltipSwatchKind(seriesName),
        };
    });

    const lineHeight = 17;
    const paddingTop = 20;
    const paddingBottom = 5;
    const width = 260;
    const height = paddingTop + 16 + rows.length * lineHeight + paddingBottom;
    sci.adjustTooltipPosition?.(width, height, svgAnnotation);

    const timeLabel = escapeSvgText(`Time: ${hits[0]?.formattedXValue ?? ''}`);
    const swatchSvg = rows.map((row, index) => {
        const y = paddingTop + 22 + index * lineHeight;
        const x = 12;
        if (row.kind === 'area') {
            return `<rect x="${x}" y="${y - 8}" width="12" height="8" rx="1.5" fill="${row.stroke}" fill-opacity="0.35" stroke="${row.stroke}" stroke-width="1"/>`;
        }
        if (row.kind === 'column') {
            return `<rect x="${x + 1}" y="${y - 9}" width="8" height="9" rx="1.2" fill="${row.stroke}" fill-opacity="0.62" stroke="${row.stroke}" stroke-width="1"/>`;
        }
        if (row.kind === 'verdict') {
            return `<circle cx="${x + 6}" cy="${y - 4}" r="3.2" fill="${row.stroke}" fill-opacity="0.7" stroke="${row.stroke}" stroke-width="1"/>`;
        }
        return `<line x1="${x}" y1="${y - 4}" x2="${x + 12}" y2="${y - 4}" stroke="${row.stroke}" stroke-width="2" stroke-dasharray="${row.dashed ? '4,3' : '0'}"/>`;
    }).join('');

    const textSvg = rows.map((row, index) => {
        const y = paddingTop + 22 + index * lineHeight;
        return `<text x="30" y="${y}" font-size="11" fill="#f8fafc">${row.label}: ${row.text}</text>`;
    }).join('');

    return `
<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
    <defs>
        <linearGradient id="tooltipGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#101b38" stop-opacity="0.95"/>
            <stop offset="100%" stop-color="#0b1227" stop-opacity="0.9"/>
        </linearGradient>
    </defs>
    <rect x="0.5" y="0.5" width="${width - 1}" height="${height - 1}" rx="8" fill="url(#tooltipGrad)" stroke="rgba(148,163,184,0.45)" stroke-width="1"/>
    <text x="12" y="${paddingTop + 2}" font-size="11" font-weight="700" fill="#e9d5ff">${timeLabel}</text>
    ${swatchSvg}
    ${textSvg}
</svg>`;
}
