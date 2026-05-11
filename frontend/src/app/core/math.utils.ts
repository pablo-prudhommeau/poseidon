export function clamp(value: number, minimum: number, maximum: number): number {
    return Math.min(maximum, Math.max(minimum, value));
}

export function linearInterpolate(start: number, end: number, weight: number): number {
    return start + (end - start) * weight;
}

export function easeOutCubic(weight: number): number {
    const clampedWeight = clamp(weight, 0, 1);
    return 1 - (1 - clampedWeight) ** 3;
}
