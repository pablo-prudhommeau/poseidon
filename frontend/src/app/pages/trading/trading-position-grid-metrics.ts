import { TradingPositionPayload, TradingTradePayload } from '../../core/models';
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
    const lastPrice = numberFormattingService.toNumberSafe(row.last_price as number | null);
    const entryPrice = numberFormattingService.toNumberSafe(row.entry_price);
    if (lastPrice === null || entryPrice === null || entryPrice === 0) {
        return null;
    }
    return ((lastPrice - entryPrice) / Math.abs(entryPrice)) * 100;
}

export function computeTradingPositionUnrealizedUsd(
    row: TradingPositionPayload | null | undefined,
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const currentQuantity = numberFormattingService.toNumberSafe(row.current_quantity);
    const lastPrice = numberFormattingService.toNumberSafe(row.last_price as number | null);
    const entryPrice = numberFormattingService.toNumberSafe(row.entry_price);
    if (currentQuantity === null || lastPrice === null || entryPrice === null) {
        return null;
    }
    return currentQuantity * (lastPrice - entryPrice);
}

export function orderTradingPositionNotionalUsd(
    row: TradingPositionPayload | null | undefined,
    priceBasis: 'entry' | 'last',
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const openQuantity = numberFormattingService.toNumberSafe(row.open_quantity);
    const price =
        priceBasis === 'entry' ? numberFormattingService.toNumberSafe(row.entry_price) : numberFormattingService.toNumberSafe(row.last_price as number | null);
    if (openQuantity === null || price === null) {
        return null;
    }
    return openQuantity * price;
}

export function remainingTradingPositionNotionalUsd(
    row: TradingPositionPayload | null | undefined,
    priceBasis: 'entry' | 'last',
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const currentQuantity = numberFormattingService.toNumberSafe(row.current_quantity);
    const price =
        priceBasis === 'entry' ? numberFormattingService.toNumberSafe(row.entry_price) : numberFormattingService.toNumberSafe(row.last_price as number | null);
    if (currentQuantity === null || price === null) {
        return null;
    }
    return currentQuantity * price;
}

export function evaluationOrderNotionalUsd(row: TradingPositionPayload | null | undefined, numberFormattingService: NumberFormattingService): number | null {
    if (!row) {
        return null;
    }
    return numberFormattingService.toNumberSafe(row.evaluation_order_notional_value_usd);
}

export function computeTradingPositionRealizedSecuredUsd(
    row: TradingPositionPayload | null | undefined,
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    return numberFormattingService.toNumberSafe(row.realized_profit_and_loss_usd);
}

export function computeTradingPositionNetResultUsd(
    row: TradingPositionPayload | null | undefined,
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const realizedSecuredUsd = computeTradingPositionRealizedSecuredUsd(row, numberFormattingService);
    const unrealizedUsd = computeTradingPositionUnrealizedUsd(row, numberFormattingService);
    if (realizedSecuredUsd === null && unrealizedUsd === null) {
        return null;
    }
    return (realizedSecuredUsd ?? 0) + (unrealizedUsd ?? 0);
}

export function computeTradingPositionEffectiveNotionalUsd(
    row: TradingPositionPayload | null | undefined,
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const evaluationNotionalUsd = evaluationOrderNotionalUsd(row, numberFormattingService);
    const netResultUsd = computeTradingPositionNetResultUsd(row, numberFormattingService);
    if (evaluationNotionalUsd === null) {
        return netResultUsd;
    }
    if (netResultUsd === null) {
        return evaluationNotionalUsd;
    }
    return evaluationNotionalUsd + netResultUsd;
}

export function resolveDeltaTickVariant(deltaPercent: number | null | undefined): DeltaTickVariant {
    if (deltaPercent == null || deltaPercent === 0) {
        return 'static';
    }
    return deltaPercent > 0 ? 'up' : 'down';
}

export function formatSignedPercentLabel(value: number | null | undefined, numberFormattingService: NumberFormattingService): string {
    if (value == null || !Number.isFinite(value)) {
        return '—';
    }
    const sign = value > 0 ? '+' : value < 0 ? '-' : '';
    return `${sign}${numberFormattingService.formatNumber(Math.abs(value), 2, 2)}%`;
}

export function formatDeltaPercentLabel(deltaPercent: number | null | undefined, numberFormattingService: NumberFormattingService): string {
    return formatSignedPercentLabel(deltaPercent, numberFormattingService);
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
    const evaluationNotionalUsd = evaluationOrderNotionalUsd(row, numberFormattingService);
    const netResultUsd = computeTradingPositionNetResultUsd(row, numberFormattingService);
    const effectiveNotionalUsd = computeTradingPositionEffectiveNotionalUsd(row, numberFormattingService);
    const evaluationNotionalLabel = evaluationNotionalUsd == null ? '—' : numberFormattingService.formatCurrency(evaluationNotionalUsd, 'USD', 0, 2);
    const effectiveNotionalLabel = effectiveNotionalUsd == null ? '—' : numberFormattingService.formatCurrency(effectiveNotionalUsd, 'USD', 0, 2);
    const liveToneClass = resolveSignedUsdLiveToneClass(netResultUsd);
    if (evaluationNotionalUsd == null && effectiveNotionalUsd == null) {
        return '—';
    }
    if (evaluationNotionalUsd == null) {
        return `<span class="${liveToneClass} poseidon-grid-emphasized-metric">${effectiveNotionalLabel}</span>`;
    }
    return `<div class="poseidon-grid-notional-stack"><span class="poseidon-grid-notional-entry-struck">${evaluationNotionalLabel}</span><span class="${liveToneClass} poseidon-grid-emphasized-metric">${effectiveNotionalLabel}</span></div>`;
}

export function formatPositionQuantityCellHtml(row: TradingPositionPayload | null | undefined, numberFormattingService: NumberFormattingService): string {
    if (row == null) {
        return '—';
    }
    const currentQuantity = numberFormattingService.toNumberSafe(row.current_quantity);
    const openQuantity = numberFormattingService.toNumberSafe(row.open_quantity);
    const currentQuantityLabel = currentQuantity == null ? '—' : numberFormattingService.formatQuantityHumanReadable(currentQuantity);
    if (currentQuantity == null || openQuantity == null || currentQuantity >= openQuantity) {
        return `<span class="poseidon-grid-emphasized-metric font-bold text-slate-100">${currentQuantityLabel}</span>`;
    }
    const openQuantityLabel = numberFormattingService.formatQuantityHumanReadable(openQuantity);
    return `<div class="poseidon-grid-notional-stack"><span class="poseidon-grid-notional-entry-struck">${openQuantityLabel}</span><span class="poseidon-grid-emphasized-metric font-bold text-slate-100">${currentQuantityLabel}</span></div>`;
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

export function formatSignedUsdLabel(valueUsd: number | null | undefined, numberFormattingService: NumberFormattingService): string {
    if (valueUsd == null || !Number.isFinite(valueUsd)) {
        return '—';
    }
    const sign = valueUsd > 0 ? '+' : valueUsd < 0 ? '-' : '';
    return `${sign}${numberFormattingService.formatCurrency(Math.abs(valueUsd), 'USD', 2, 2)}`;
}

export function formatDeltaPercentAndUsdCellHtml(row: TradingPositionPayload | null | undefined, numberFormattingService: NumberFormattingService): string {
    const deltaPercent = computeTradingPositionDeltaPercent(row, numberFormattingService);
    const unrealizedUsd = computeTradingPositionUnrealizedUsd(row, numberFormattingService);
    const percentHtml = formatDeltaPercentCellHtml(deltaPercent, numberFormattingService);
    const usdToneClass = resolveSignedUsdLiveToneClass(unrealizedUsd);
    const usdLabel = formatSignedUsdLabel(unrealizedUsd, numberFormattingService);
    return `<div class="poseidon-grid-delta-stack">${percentHtml}<span class="${usdToneClass} poseidon-grid-delta-usd">${usdLabel}</span></div>`;
}

export function computeTradeSecuredProfitAndLossEvaluationPercent(
    row: TradingTradePayload | null | undefined,
    numberFormattingService: NumberFormattingService
): number | null {
    if (!row) {
        return null;
    }
    const realizedProfitAndLoss = numberFormattingService.toNumberSafe(row.realized_profit_and_loss ?? null);
    if (realizedProfitAndLoss === null || realizedProfitAndLoss === 0) {
        return null;
    }
    const evaluationOrderNotionalValueUsd = numberFormattingService.toNumberSafe(row.evaluation_order_notional_value_usd ?? null);
    if (evaluationOrderNotionalValueUsd === null || evaluationOrderNotionalValueUsd <= 0) {
        return null;
    }
    return (realizedProfitAndLoss / evaluationOrderNotionalValueUsd) * 100;
}

export function buildTradeSecuredProfitAndLossEvaluationPercentTooltip(
    row: TradingTradePayload | null | undefined,
    numberFormattingService: NumberFormattingService
): string {
    const evaluationOrderNotionalValueUsd = numberFormattingService.toNumberSafe(row?.evaluation_order_notional_value_usd ?? null);
    if (evaluationOrderNotionalValueUsd === null) {
        return '';
    }
    const formattedEvaluationBase = numberFormattingService.formatCurrency(evaluationOrderNotionalValueUsd, 'USD', 2, 2);
    return `Secured profit and loss as a percentage of the evaluation order notional (${formattedEvaluationBase})`;
}

export function resolveSignedProfitAndLossToneClass(realizedProfitAndLoss: number | null): string {
    if (realizedProfitAndLoss === null || realizedProfitAndLoss === 0) {
        return 'text-slate-400';
    }
    if (realizedProfitAndLoss > 0) {
        return 'text-emerald-400';
    }
    return 'text-rose-400';
}

export function formatTradeRealizedProfitAndLossCellHtml(
    row: TradingTradePayload | null | undefined,
    numberFormattingService: NumberFormattingService
): string {
    const realizedProfitAndLoss = numberFormattingService.toNumberSafe(row?.realized_profit_and_loss ?? null);
    const realizedProfitAndLossPercent = computeTradeSecuredProfitAndLossEvaluationPercent(row, numberFormattingService);
    const toneClass = resolveSignedProfitAndLossToneClass(realizedProfitAndLoss);
    const usdLabel = realizedProfitAndLoss === null ? '—' : formatSignedUsdLabel(realizedProfitAndLoss, numberFormattingService);
    const usdHtml = `<span class="poseidon-grid-delta-usd ${toneClass}">${usdLabel}</span>`;
    if (realizedProfitAndLossPercent === null) {
        return `<span class="poseidon-grid-emphasized-metric ${toneClass}">${usdLabel}</span>`;
    }
    const percentLabel = formatSignedPercentLabel(realizedProfitAndLossPercent, numberFormattingService);
    const percentHtml = `<span class="poseidon-grid-emphasized-metric ${toneClass}">${percentLabel}</span>`;
    return `<div class="poseidon-grid-delta-stack">${percentHtml}${usdHtml}</div>`;
}
