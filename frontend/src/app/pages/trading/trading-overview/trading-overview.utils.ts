export function mapNullable<TSource, TProjected>(
    value: TSource | null | undefined,
    mapper: (value: TSource) => TProjected
): Exclude<TProjected, undefined> | null {
    if (value === null || value === undefined) {
        return null;
    }
    const projected = mapper(value);
    return projected === undefined ? null : (projected as Exclude<TProjected, undefined>);
}

export function firstNonNull(...values: Array<number | null>): number | null {
    for (const value of values) {
        if (value !== null) {
            return value;
        }
    }
    return null;
}

export function computeProgressPercentage(value: number | null | undefined, required: number | null | undefined): number {
    if (required === null || required === undefined || required <= 0) {
        return 100;
    }
    return Math.min(100, ((value ?? 0) / required) * 100);
}

export function safePercent(value: number | null | undefined, base: number | null | undefined): number | null {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return null;
    }
    if (base === null || base === undefined || !Number.isFinite(base) || base <= 0) {
        return null;
    }
    return (value / base) * 100;
}

export function isNonNegative(value: number | null): boolean {
    if (value === null) {
        return false;
    }
    return value >= 0;
}

export function formatUsdValue(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return '—';
    }
    return `$ ${value.toFixed(2)}`;
}

export function formatMultiplier(value: number | null | undefined): string {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return '—';
    }
    if (value >= 900) {
        return '999+';
    }
    return value.toFixed(2);
}

export function formatShadowingMetricLookbackDays(days: number): string {
    if (Number.isInteger(days)) {
        return String(days);
    }
    const rounded = Math.round(days * 10) / 10;
    return rounded % 1 === 0 ? String(Math.round(rounded)) : rounded.toFixed(1);
}

export function formatHumanDurationFromSeconds(totalSeconds: number): string {
    if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) {
        return '—';
    }
    if (totalSeconds < 60) {
        const seconds = Math.round(totalSeconds);
        return `${seconds} ${seconds > 1 ? 'seconds' : 'second'}`;
    }
    if (totalSeconds < 3600) {
        const minutes = Math.round(totalSeconds / 60);
        return `${minutes} ${minutes > 1 ? 'minutes' : 'minute'}`;
    }
    if (totalSeconds < 86400) {
        const hours = totalSeconds / 3600;
        const rounded = Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
        return `${rounded} ${hours > 1 ? 'hours' : 'hour'}`;
    }
    const days = totalSeconds / 86400;
    const rounded = Number.isInteger(days) ? String(days) : days.toFixed(1);
    return `${rounded} ${days > 1 ? 'days' : 'day'}`;
}

export function formatHumanDurationFromDays(days: number): string {
    if (!Number.isFinite(days) || days <= 0) {
        return '—';
    }
    return formatHumanDurationFromSeconds(days * 86400);
}

export function deriveShadowEdgeGateSatisfied(
    chronicleProfitFactor: number | null | undefined,
    chronicleProfitFactorThreshold: number | null | undefined,
    sparseExpectedValueUsd: number | null | undefined,
    sparseExpectedValueUsdThreshold: number | null | undefined
): boolean {
    if (
        chronicleProfitFactor === null ||
        chronicleProfitFactor === undefined ||
        chronicleProfitFactorThreshold === null ||
        chronicleProfitFactorThreshold === undefined ||
        sparseExpectedValueUsd === null ||
        sparseExpectedValueUsd === undefined ||
        sparseExpectedValueUsdThreshold === null ||
        sparseExpectedValueUsdThreshold === undefined
    ) {
        return false;
    }
    return chronicleProfitFactor >= chronicleProfitFactorThreshold && sparseExpectedValueUsd >= sparseExpectedValueUsdThreshold;
}
