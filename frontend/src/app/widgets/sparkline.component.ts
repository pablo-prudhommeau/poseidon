import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Minimalist sparkline (SVG).
 *
 * Accepts either:
 *   - y-only values: number | string
 *   - time series tuples: [timestampMs, value]
 *
 * No object shapes are supported (e.g., { t, v }).
 */
type SparklinePoint = number | string | null | undefined | [number, number];

@Component({
    standalone: true,
    selector: 'sparkline',
    templateUrl: './sparkline.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SparklineComponent {
    /** Series points (y-only or [ts, y]) as a reactive input. */
    public readonly points = input<SparklinePoint[]>([]);

    /** ViewBox size as reactive inputs. */
    public readonly width = input<number>(120);
    public readonly height = input<number>(36);

    /** Inner padding (px) as a reactive input. */
    public readonly padding = input<number>(2);

    /**
     * Sanitized numeric Y values extracted from the input series.
     * This is reactive because it reads from signal inputs.
     */
    public readonly sanitizedPoints = computed<number[]>(() => {
        const raw = this.points() ?? [];
        const out: number[] = [];

        for (const p of raw) {
            if (p == null) continue;

            // Primitive -> number
            if (typeof p === 'number') {
                if (Number.isFinite(p)) out.push(p);
                continue;
            }
            if (typeof p === 'string') {
                const n = Number(p);
                if (Number.isFinite(n)) out.push(n);
                continue;
            }

            // Tuple [ts, value]
            if (Array.isArray(p) && p.length >= 2) {
                const n = Number(p[1]);
                if (Number.isFinite(n)) out.push(n);
            }
        }
        return out;
    });

    /**
     * Builds the SVG path for the sparkline.
     * Recomputes when points/width/height/padding change.
     */
    public readonly pathData = computed<string>(() => {
        const pts = this.sanitizedPoints();
        const w = Math.max(1, (this.width() | 0));
        const h = Math.max(1, (this.height() | 0));
        const p = Math.max(0, (this.padding() | 0));

        if (!pts || pts.length < 2) {
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
            const y = h - p - t * innerH; // invert Y
            return clamp(round2(y), p, h - p);
        };

        // Path
        const cmds = pts.map((v, i) => {
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
