import {ChangeDetectionStrategy, Component, computed, input} from '@angular/core';

export type SparklinePoint = number | string | null | undefined | [number, number] | { equity: number, [k: string]: any } | { total_equity_value: number, [k: string]: any };

@Component({
    standalone: true,
    selector: 'sparkline',
    templateUrl: './sparkline.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SparklineComponent {
    public readonly points = input<SparklinePoint[]>([]);
    public readonly width = input<number>(120);
    public readonly height = input<number>(36);
    public readonly padding = input<number>(2);

    public readonly normalizedPoints = computed<number[]>(() => {
        const rawPoints = this.points() ?? [];
        const extractedValues: number[] = [];

        for (const point of rawPoints) {
            if (point === null || point === undefined) {
                continue;
            }

            if (typeof point === 'number') {
                if (Number.isFinite(point)) {
                    extractedValues.push(point);
                }
                continue;
            }

            if (typeof point === 'string') {
                const parsedValue = Number(point);
                if (Number.isFinite(parsedValue)) {
                    extractedValues.push(parsedValue);
                }
                continue;
            }

            if (Array.isArray(point) && point.length >= 2) {
                const parsedValue = Number(point[1]);
                if (Number.isFinite(parsedValue)) {
                    extractedValues.push(parsedValue);
                }
                continue;
            }

            if (typeof point === 'object' && 'equity' in point) {
                const parsedValue = Number(point.equity);
                if (Number.isFinite(parsedValue)) {
                    extractedValues.push(parsedValue);
                }
                continue;
            }

            if (typeof point === 'object' && 'total_equity_value' in point) {
                const parsedValue = Number(point.total_equity_value);
                if (Number.isFinite(parsedValue)) {
                    extractedValues.push(parsedValue);
                }
            }
        }

        return extractedValues;
    });

    public readonly svgPathDefinition = computed<string>(() => {
        const points = this.normalizedPoints();
        const canvasWidth = Math.max(1, Math.floor(this.width()));
        const canvasHeight = Math.max(1, Math.floor(this.height()));
        const innerPadding = Math.max(0, Math.floor(this.padding()));

        if (points.length < 2) {
            const verticalCenter = Math.round(canvasHeight / 2);
            return `M 0 ${verticalCenter} L ${canvasWidth} ${verticalCenter}`;
        }

        const minimumValue = Math.min(...points);
        const maximumValue = Math.max(...points);

        if (maximumValue === minimumValue) {
            const verticalCenter = this.clampValue(
                Math.round(canvasHeight / 2),
                innerPadding,
                canvasHeight - innerPadding
            );
            return `M ${innerPadding} ${verticalCenter} L ${canvasWidth - innerPadding} ${verticalCenter}`;
        }

        const drawableWidth = Math.max(1, canvasWidth - 2 * innerPadding);
        const drawableHeight = Math.max(1, canvasHeight - 2 * innerPadding);
        const range = maximumValue - minimumValue;
        const horizontalStep = drawableWidth / (points.length - 1);

        const calculateVerticalPosition = (value: number): number => {
            const normalizedValue = (value - minimumValue) / range;
            const verticalCoordinate = canvasHeight - innerPadding - normalizedValue * drawableHeight;
            return this.clampValue(
                this.roundToTwoDecimalPlaces(verticalCoordinate),
                innerPadding,
                canvasHeight - innerPadding
            );
        };

        const pathCommands = points.map((value, index) => {
            const horizontalCoordinate = this.roundToTwoDecimalPlaces(innerPadding + index * horizontalStep);
            const verticalCoordinate = calculateVerticalPosition(value);
            const commandType = index === 0 ? 'M' : 'L';
            return `${commandType} ${horizontalCoordinate} ${verticalCoordinate}`;
        });

        return pathCommands.join(' ');
    });

    private clampValue(value: number, lowerBound: number, upperBound: number): number {
        return Math.min(upperBound, Math.max(lowerBound, value));
    }

    private roundToTwoDecimalPlaces(value: number): number {
        return Math.round(value * 100) / 100;
    }
}