import { Component, computed, Input } from '@angular/core';

/**
 * Sparkline (SVG).
 * Accepte: number | string (liste de Y) OU [timestamp, value] (timeseries).
 * Aucun objet {t,v} / {value}.
 */
@Component({
    standalone: true,
    selector: 'sparkline',
    templateUrl: './sparkline.component.html',
})
export class SparklineComponent {
    /** Série: Y-only (number|string) ou tuples [ts, value]. */
    @Input() points: Array<number | string | null | undefined | [number, number]> = [];

    /** ViewBox size */
    @Input() width = 120;
    @Input() height = 36;

    /** Inner padding (px) */
    @Input() padding = 2;

    /** Y normalisés */
    public readonly sanitizedPoints = computed<number[]>(() => {
        const out: number[] = [];
        for (const p of this.points ?? []) {
            if (p == null) continue;

            // primitive -> number
            if (typeof p === 'number') {
                if (Number.isFinite(p)) out.push(p);
                continue;
            }
            if (typeof p === 'string') {
                const n = Number(p);
                if (Number.isFinite(n)) out.push(n);
                continue;
            }

            // tuple [ts, value]
            if (Array.isArray(p) && p.length >= 2) {
                const n = Number(p[1]);
                if (Number.isFinite(n)) out.push(n);
            }
        }
        return out;
    });

    /** Construit le chemin SVG */
    public readonly pathData = computed<string>(() => {
        const pts = this.sanitizedPoints();
        const w = Math.max(1, this.width | 0);
        const h = Math.max(1, this.height | 0);
        const p = Math.max(0, this.padding | 0);

        if (!pts || pts.length < 2) {
            const midY = Math.round(h / 2);
            return `M 0 ${midY} L ${w} ${midY}`;
        }

        // bornes
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

        // échelles
        const innerW = Math.max(1, w - 2 * p);
        const innerH = Math.max(1, h - 2 * p);
        const safeRange = max - min;
        const stepX = innerW / (pts.length - 1);

        const scaleY = (v: number) => {
            const t = (v - min) / safeRange;
            const y = h - p - t * innerH; // invert Y
            return clamp(round2(y), p, h - p);
        };

        // path
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
