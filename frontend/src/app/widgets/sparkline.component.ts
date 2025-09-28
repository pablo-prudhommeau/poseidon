import {Component, computed, Input} from '@angular/core';

@Component({
    standalone: true,
    selector: 'sparkline',
    templateUrl: './sparkline.component.html'
})
export class SparklineComponent {
    @Input() points: Array<number | string | null | undefined> = [];

    @Input() width = 120;
    @Input() height = 36;

    @Input() padding = 2;

    public readonly sanitizedPoints = computed<number[]>(() => {
        const raw = this.points ?? [];
        const nums = raw
            .map((v) =>
                typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
            )
            .filter((v) => Number.isFinite(v));
        return nums;
    });

    public readonly pathData = computed<string>(() => {
        const pts = this.sanitizedPoints();
        const w = Math.max(1, Math.floor(this.width || 0));
        const h = Math.max(1, Math.floor(this.height || 0));
        const p = Math.max(0, Math.floor(this.padding || 0));

        if (pts.length < 2) {
            const mid = clamp(Math.round(h / 2), p, h - p);
            return `M 0 ${mid} L ${w} ${mid}`;
        }

        let min = Math.min(...pts);
        let max = Math.max(...pts);
        if (!Number.isFinite(min) || !Number.isFinite(max)) {
            min = 0;
            max = 1;
        }

        const range = max - min;
        const safeRange = range === 0 ? 1 : range;

        const innerW = Math.max(1, w - p * 2);
        const innerH = Math.max(1, h - p * 2);
        const stepX = innerW / (pts.length - 1);

        const scaleY = (v: number) => {
            const t = (v - min) / safeRange;
            const y = h - p - t * innerH;
            return clamp(round2(y), p, h - p);
        };

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
