import { Component, computed, Input } from '@angular/core';

/**
 * Lightweight sparkline component (SVG only).
 * - Accepts points in various shapes: number | string | [ts, value] | { v } | { t, v } | { value }
 * - Computes a compact SVG path scaled to provided width/height
 * - Falls back to a centered flat line if there are < 2 valid points
 */
@Component({
    standalone: true,
    selector: 'sparkline',
    templateUrl: './sparkline.component.html',
})
export class SparklineComponent {
    /** Input series; supports numbers or common object/tuple shapes. */
    @Input() points: Array<
        | number
        | string
        | null
        | undefined
        | [number, number]
        | { v?: number | string; value?: number | string; t?: number | string }
        | { t: number | string; v: number | string }
    > = [];

    /** ViewBox size */
    @Input() width = 120;
    @Input() height = 36;

    /** Inner padding in pixels */
    @Input() padding = 2;

    /**
     * Normalized numeric series (Y values only).
     * - Extracts numbers from diverse input shapes
     * - Filters invalid/NaN values
     */
    public readonly sanitizedPoints = computed<number[]>(() => {
        const out: number[] = [];
        for (const p of this.points ?? []) {
            if (p == null) continue;

            // primitive -> number
            if (typeof p === 'number') {
                if (isFinite(p)) out.push(p);
                continue;
            }
            if (typeof p === 'string') {
                const n = Number(p);
                if (isFinite(n)) out.push(n);
                continue;
            }

            // tuple [ts, value]
            if (Array.isArray(p) && p.length >= 2) {
                const n = Number(p[1]);
                if (isFinite(n)) out.push(n);
                continue;
            }

            // object shapes: { v }, { t, v }, { value }
            if (typeof p === 'object') {
                const any = p as Record<string, unknown>;
                const candidate =
                    any?.v ?? any?.value ?? (Array.isArray(any) && any[1] !== undefined ? any[1] : undefined);
                const n = Number(candidate);
                if (isFinite(n)) out.push(n);
            }
        }
        return out;
    });

    /**
     * Build the SVG path string from sanitized Y values.
     */
    public readonly pathData = computed<string>(() => {
        const pts = this.sanitizedPoints();
        const w = Math.max(1, this.width | 0);
        const h = Math.max(1, this.height | 0);
        const p = Math.max(0, this.padding | 0);

        if (!pts || pts.length < 2) {
            // Graceful fallback: centered flat line
            const midY = Math.round(h / 2);
            return `M 0 ${midY} L ${w} ${midY}`;
        }

        // Bounds
        let min = pts[0];
        let max = pts[0];
        for (let i = 1; i < pts.length; i++) {
            const v = pts[i];
            if (v < min) min = v;
            if (v > max) max = v;
        }
        if (max === min) {
            // Flat series; draw a flat line scaled inside padding
            const y = clamp(Math.round(h / 2), p, h - p);
            return `M ${p} ${y} L ${w - p} ${y}`;
        }

        // Scales
        const innerW = Math.max(1, w - 2 * p);
        const innerH = Math.max(1, h - 2 * p);
        const safeRange = max - min;
        const stepX = innerW / (pts.length - 1);

        const scaleY = (v: number) => {
            const t = (v - min) / safeRange;
            const y = h - p - t * innerH; // invert Y for SVG
            return clamp(round2(y), p, h - p);
        };

        // Path
        const cmds: string[] = pts.map((v, i) => {
            const x = round2(p + i * stepX);
            const y = scaleY(v);
            return `${i ? 'L' : 'M'} ${x} ${y}`;
        });

        return cmds.join(' ');
    });
}

function clamp(v: number, lo: number, hi: number): number {
    return Math.min(hi, Math.max(lo, v));
}

function round2(n: number): number {
    return Math.round(n * 100) / 100;
}
