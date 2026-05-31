import { TradingPositionPayload } from '../../core/models';
import { NumberFormattingService } from '../../core/number-formatting.service';

export type DeltaTickVariant = 'static' | 'up' | 'down';

export function computeTradingPositionDeltaPercent(
    row: TradingPositionPayload | null | undefined,
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const enriched = numberFormattingService.toNumberSafe((row as { priceChangePercent?: number | null }).priceChangePercent ?? null);
    if (enriched !== null) {
        return enriched;
    }
    const last = numberFormattingService.toNumberSafe(row.last_price as number | null);
    const entry = numberFormattingService.toNumberSafe(row.entry_price);
    if (last === null || entry === null || entry === 0) {
        return null;
    }
    return ((last - entry) / Math.abs(entry)) * 100;
}

export function orderTradingPositionNotionalUsd(
    row: TradingPositionPayload | null | undefined,
    priceBasis: 'entry' | 'last',
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const quantity = numberFormattingService.toNumberSafe(row.open_quantity);
    const price =
        priceBasis === 'entry' ? numberFormattingService.toNumberSafe(row.entry_price) : numberFormattingService.toNumberSafe(row.last_price as number | null);
    if (quantity === null || price === null) {
        return null;
    }
    return quantity * price;
}

export function remainingTradingPositionNotionalUsd(
    row: TradingPositionPayload | null | undefined,
    priceBasis: 'entry' | 'last',
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const quantity = numberFormattingService.toNumberSafe(row.current_quantity);
    const price =
        priceBasis === 'entry' ? numberFormattingService.toNumberSafe(row.entry_price) : numberFormattingService.toNumberSafe(row.last_price as number | null);
    if (quantity === null || price === null) {
        return null;
    }
    return quantity * price;
}

export function resolveDeltaTickVariant(deltaPercent: number | null | undefined): DeltaTickVariant {
    if (deltaPercent == null || deltaPercent === 0) {
        return 'static';
    }
    return deltaPercent > 0 ? 'up' : 'down';
}

export function formatDeltaPercentLabel(deltaPercent: number | null | undefined, numberFormattingService: NumberFormattingService): string {
    if (deltaPercent == null) {
        return '—';
    }
    return `${numberFormattingService.formatNumber(deltaPercent, 2, 2)}%`;
}

export function resolveNotionalLiveToneClass(deltaPercent: number | null | undefined): string {
    if (deltaPercent != null && deltaPercent > 0) {
        return 'poseidon-grid-notional-live poseidon-grid-notional-live--positive';
    }
    if (deltaPercent != null && deltaPercent < 0) {
        return 'poseidon-grid-notional-live poseidon-grid-notional-live--negative';
    }
    return 'poseidon-grid-notional-live poseidon-grid-notional-live--neutral';
}

export function resolveSignedUsdLiveToneClass(valueUsd: number | null | undefined): string {
    if (valueUsd == null || valueUsd === 0) {
        return 'poseidon-grid-notional-live poseidon-grid-notional-live--neutral';
    }
    if (valueUsd > 0) {
        return 'poseidon-grid-notional-live poseidon-grid-notional-live--positive';
    }
    return 'poseidon-grid-notional-live poseidon-grid-notional-live--negative';
}

export function formatPositionNotionalCellHtml(row: TradingPositionPayload | null | undefined, numberFormattingService: NumberFormattingService): string {
    if (row == null) {
        return '—';
    }
    const entryNotionalUsd = orderTradingPositionNotionalUsd(row, 'entry', numberFormattingService);
    const lastNotionalUsd = orderTradingPositionNotionalUsd(row, 'last', numberFormattingService);
    const entryNotionalLabel = entryNotionalUsd == null ? '—' : numberFormattingService.formatCurrency(entryNotionalUsd, 'USD', 0, 2);
    const lastNotionalLabel = lastNotionalUsd == null ? '—' : numberFormattingService.formatCurrency(lastNotionalUsd, 'USD', 0, 2);
    const liveToneClass = resolveNotionalLiveToneClass(computeTradingPositionDeltaPercent(row, numberFormattingService));
    if (entryNotionalUsd == null && lastNotionalUsd == null) {
        return '—';
    }
    if (entryNotionalUsd == null) {
        return `<span class="${liveToneClass} poseidon-grid-emphasized-metric">${lastNotionalLabel}</span>`;
    }
    return `<div class="poseidon-grid-notional-stack"><span class="poseidon-grid-notional-entry-struck">${entryNotionalLabel}</span><span class="${liveToneClass} poseidon-grid-emphasized-metric">${lastNotionalLabel}</span></div>`;
}

export function formatDeltaPercentCellHtml(deltaPercent: number | null | undefined, numberFormattingService: NumberFormattingService): string {
    const displayedValue = formatDeltaPercentLabel(deltaPercent, numberFormattingService);
    const variant = resolveDeltaTickVariant(deltaPercent);
    if (variant === 'static') {
        return `<span class="delta-static font-semibold text-slate-400 poseidon-grid-emphasized-metric">${displayedValue}</span>`;
    }
    if (variant === 'up') {
        return `<span class="delta-tick delta-tick-up font-bold"><span class="delta-arrow" aria-hidden="true">↗</span><span class="poseidon-grid-emphasized-metric">${displayedValue}</span></span>`;
    }
    return `<span class="delta-tick delta-tick-down font-bold"><span class="delta-arrow" aria-hidden="true">↘</span><span class="poseidon-grid-emphasized-metric">${displayedValue}</span></span>`;
}
