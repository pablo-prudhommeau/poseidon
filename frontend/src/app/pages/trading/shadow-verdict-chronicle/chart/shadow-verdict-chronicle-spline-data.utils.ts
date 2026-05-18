import { linearInterpolate } from '../../../../core/math.utils';

interface SplineSafeXyValues {
    xValues: number[];
    yValues: number[];
}

export function buildSplineSafeXyValues(rawXValues: number[], rawYValues: number[]): SplineSafeXyValues {
    const xValues: number[] = [];
    const yValues: number[] = [];
    for (let index = 0; index < rawXValues.length; index++) {
        const xValue = rawXValues[index];
        if (!Number.isFinite(xValue) || (xValues.length > 0 && xValue <= xValues[xValues.length - 1])) {
            continue;
        }
        xValues.push(xValue);
        yValues.push(rawYValues[index] ?? NaN);
    }

    const finiteIndices = yValues.reduce<number[]>((accumulator, value, index) => {
        if (Number.isFinite(value)) {
            accumulator.push(index);
        }
        return accumulator;
    }, []);
    if (finiteIndices.length < 2) {
        return { xValues: [], yValues: [] };
    }

    const firstFiniteIndex = finiteIndices[0];
    const lastFiniteIndex = finiteIndices[finiteIndices.length - 1];
    for (let index = 0; index < firstFiniteIndex; index++) {
        yValues[index] = yValues[firstFiniteIndex];
    }
    for (let index = lastFiniteIndex + 1; index < yValues.length; index++) {
        yValues[index] = yValues[lastFiniteIndex];
    }
    for (let finiteIndex = 0; finiteIndex < finiteIndices.length - 1; finiteIndex++) {
        const leftIndex = finiteIndices[finiteIndex];
        const rightIndex = finiteIndices[finiteIndex + 1];
        const span = xValues[rightIndex] - xValues[leftIndex];
        if (span <= 0) {
            continue;
        }
        for (let index = leftIndex + 1; index < rightIndex; index++) {
            const weight = (xValues[index] - xValues[leftIndex]) / span;
            yValues[index] = linearInterpolate(yValues[leftIndex], yValues[rightIndex], weight);
        }
    }

    return { xValues, yValues };
}
