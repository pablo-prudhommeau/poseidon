// frontend/src/app/apex.theme.ts

/** Palette Poseidon */
export const POSEIDON_COLORS = {
    background: '#0b1020',
    surface: '#111634',
    text: '#e5e7eb',
    textDim: '#9ca3af',
    primary: '#7c5cff',
    primaryAlt: '#ff7ac3',
    accent: '#22d3ee',
    success: '#22c55e',
    warning: '#f59e0b',
    danger: '#ef4444'
};

/** Thème de base optimisé perfs (Apex 5.3.5 + ng-apexcharts) */
export function baseTheme() {
    return {
        chart: {
            type: 'line' as const,
            background: 'transparent',
            foreColor: POSEIDON_COLORS.text,
            toolbar: {show: false},
            dropShadow: {enabled: false},
            animations: {enabled: false},
            zoom: {enabled: false},
            fontFamily: 'inherit'
        },
        grid: {
            borderColor: 'rgba(255,255,255,0.06)',
            strokeDashArray: 3,
            xaxis: {lines: {show: false}},
            padding: {left: 6, right: 6, top: 8, bottom: 0}
        },
        legend: {
            show: true,
            fontSize: '12px',
            labels: {colors: POSEIDON_COLORS.text, useSeriesColors: false},
            itemMargin: {horizontal: 12, vertical: 6}
        },
        tooltip: {theme: 'dark', fillSeriesColor: false, shared: false, intersect: true},
        dataLabels: {enabled: false, style: {fontSize: '12px'}},
        states: {
            hover: {filter: {type: 'none', value: 0}},
            active: {filter: {type: 'none', value: 0}}
        },
        markers: {size: 2, strokeWidth: 0, strokeOpacity: 0},
        stroke: {width: 2, curve: 'straight' as const},
        fill: {opacity: 1},
        colors: [
            POSEIDON_COLORS.primary,
            POSEIDON_COLORS.accent,
            POSEIDON_COLORS.primaryAlt,
            POSEIDON_COLORS.success,
            POSEIDON_COLORS.warning,
            POSEIDON_COLORS.danger
        ]
    };
}

/** Exports legacy si tu les appelles ailleurs */
export function areaStyle() { return {...baseTheme(), chart: {...baseTheme().chart, type: 'area' as const}}; }

export function columnStyle() { return {...baseTheme(), chart: {...baseTheme().chart, type: 'bar' as const}}; }

export function heatmapStyle() { return {...baseTheme(), chart: {...baseTheme().chart, type: 'heatmap' as const}}; }
