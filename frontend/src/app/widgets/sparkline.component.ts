import {NgIf} from '@angular/common';
import {Component, Input, OnChanges} from '@angular/core';

@Component({
    standalone: true,
    selector: 'sparkline',
    imports: [
        NgIf
    ],
    templateUrl: 'sparkline.component.html'
})
export class SparklineComponent implements OnChanges {
    @Input() data: number[] = [];
    @Input() width = 220;
    @Input() height = 40;

    path = '';

    ngOnChanges(): void {
        this.path = this.buildPath(this.data);
    }

    private buildPath(values: number[]): string {
        if (!values?.length) {
            return '';
        }
        const w = this.width, h = this.height;
        const min = Math.min(...values);
        const max = Math.max(...values);
        const span = max - min || 1;

        const x = (i: number) => (i / (values.length - 1)) * w;
        const y = (v: number) => h - ((v - min) / span) * h;

        let d = `M ${x(0)} ${y(values[0])}`;
        for (let i = 1; i < values.length; i++) {
            d += ` L ${x(i)} ${y(values[i])}`;
        }
        return d;
    }
}
