import { GasRefillBudgetDetailScope, GasRefillLockedBreakdownPayload } from '../../../core/models';

export interface GasRefillLockedTooltipContext {
    nativeTokenSymbol: string;
    isPaperMode: boolean;
    lockedStablecoinUsd: number;
    breakdown?: GasRefillLockedBreakdownPayload;
    gasRefillBudgetDetailScope?: GasRefillBudgetDetailScope;
}

const LOCKED_GUARDRAIL_LEAD_PARAGRAPH = 'Stablecoin withheld from deployable cash to guarantee a full native gas refill.';

const SOLANA_CHAIN_BUDGET_DETAIL_PARAGRAPH = 'Each open position reserves SPL token account rent plus swap fees for entry, first take-profit, and exit.';

const EVM_CHAIN_BUDGET_DETAIL_PARAGRAPH = 'Each open position reserves swap fees for entry, first take-profit, and exit.';

function buildBreakdownRowHtml(label: string, valueHtml: string): string {
    return (
        `<p class="poseidon-tooltip-body mb-1.5 flex items-baseline justify-between gap-4 text-slate-200">` +
        `<span class="poseidon-tooltip-label shrink-0">${label}</span>` +
        `${valueHtml}` +
        `</p>`
    );
}

function formatNativeWithUsd(nativeRaw: number, nativeSymbol: string, usd: number): string {
    return (
        `<span class="inline-flex items-center justify-end gap-1.5 whitespace-nowrap tabular-nums">` +
        `${nativeRaw.toFixed(4)} ${nativeSymbol}` +
        `<span class="poseidon-tooltip-rent-separator" aria-hidden="true">·</span>` +
        `$ ${usd.toFixed(2)}` +
        `</span>`
    );
}

function formatMaxPositionsQualifier(maxOpenPositions: number): string {
    const noun = maxOpenPositions === 1 ? 'max position' : 'max positions';
    return `<span class="poseidon-tooltip-muted">${maxOpenPositions} ${noun}</span>`;
}

function formatCycleQualifier(cycleCount: number): string {
    return `<span class="poseidon-tooltip-muted">×${cycleCount} cycles</span>`;
}

function formatQualifiedNativeValue(qualifierHtml: string, nativeRaw: number, nativeSymbol: string, usd: number): string {
    return (
        `<span class="inline-flex items-center justify-end gap-1.5 whitespace-nowrap">` +
        `${qualifierHtml}` +
        `<span class="poseidon-tooltip-rent-separator" aria-hidden="true">·</span>` +
        `${formatNativeWithUsd(nativeRaw, nativeSymbol, usd)}` +
        `</span>`
    );
}

function formatLockedUsd(lockedUsd: number): string {
    const emphasisClass = lockedUsd > 0 ? 'font-semibold text-cyan-100' : 'tabular-nums';
    return `<span class="${emphasisClass}">$ ${lockedUsd.toFixed(2)}</span>`;
}

function resolveChainBudgetDetailParagraph(gasRefillBudgetDetailScope: GasRefillBudgetDetailScope | undefined): string | null {
    if (gasRefillBudgetDetailScope === 'solana_with_token_account_rent') {
        return SOLANA_CHAIN_BUDGET_DETAIL_PARAGRAPH;
    }
    if (gasRefillBudgetDetailScope === 'evm_swap_fees_only') {
        return EVM_CHAIN_BUDGET_DETAIL_PARAGRAPH;
    }
    return null;
}

function buildLockedIntroHtml(context: GasRefillLockedTooltipContext): string {
    const chainBudgetDetailParagraph = resolveChainBudgetDetailParagraph(context.gasRefillBudgetDetailScope);
    if (chainBudgetDetailParagraph === null) {
        return `<p class="poseidon-tooltip-body mb-3 text-slate-200">${LOCKED_GUARDRAIL_LEAD_PARAGRAPH}</p>`;
    }
    return (
        `<p class="poseidon-tooltip-body mb-2 text-slate-200">${LOCKED_GUARDRAIL_LEAD_PARAGRAPH}</p>` +
        `<p class="poseidon-tooltip-body mb-3 text-slate-200">${chainBudgetDetailParagraph}</p>`
    );
}

function buildBreakdownTooltipHtml(context: GasRefillLockedTooltipContext): string {
    const breakdown = context.breakdown;
    if (breakdown === undefined) {
        return buildFallbackTooltipHtml(context);
    }

    const nativeSymbol = context.nativeTokenSymbol;

    return (
        `<p class="mb-2"><span class="poseidon-tooltip-title text-cyan-200">locked</span></p>` +
        `${buildLockedIntroHtml(context)}` +
        `${buildBreakdownRowHtml('per position', formatNativeWithUsd(breakdown.per_position_cycle_cost_native_raw, nativeSymbol, breakdown.per_position_cycle_cost_usd))}` +
        `${buildBreakdownRowHtml('portfolio', formatQualifiedNativeValue(formatMaxPositionsQualifier(breakdown.max_open_positions), breakdown.portfolio_cycle_cost_native_raw, nativeSymbol, breakdown.portfolio_cycle_cost_usd))}` +
        `${buildBreakdownRowHtml('target reserve', formatQualifiedNativeValue(formatCycleQualifier(breakdown.refill_target_cycle_count), breakdown.refill_target_budget_native_raw, nativeSymbol, breakdown.refill_target_budget_usd))}` +
        `${buildBreakdownRowHtml('current gas', formatNativeWithUsd(breakdown.native_gas_balance_raw, nativeSymbol, breakdown.native_gas_balance_usd))}` +
        `${buildBreakdownRowHtml('auto-refill below', formatQualifiedNativeValue(formatCycleQualifier(breakdown.refill_trigger_cycle_count), breakdown.refill_trigger_threshold_native_raw, nativeSymbol, breakdown.refill_trigger_threshold_usd))}`
    );
}

function buildFallbackTooltipHtml(context: GasRefillLockedTooltipContext): string {
    if (context.isPaperMode) {
        return (
            `<p class="mb-2"><span class="poseidon-tooltip-title text-cyan-200">locked</span></p>` +
            `<p class="poseidon-tooltip-body text-slate-200">Gas refill reserve is not tracked in paper mode.</p>`
        );
    }

    const chainBudgetDetailParagraph = resolveChainBudgetDetailParagraph(context.gasRefillBudgetDetailScope);
    const chainDetailHtml = chainBudgetDetailParagraph === null ? '' : `<p class="poseidon-tooltip-body mb-3 text-slate-200">${chainBudgetDetailParagraph}</p>`;

    return (
        `<p class="mb-2"><span class="poseidon-tooltip-title text-cyan-200">locked</span></p>` +
        `<p class="poseidon-tooltip-body mb-2 text-slate-200">${LOCKED_GUARDRAIL_LEAD_PARAGRAPH}</p>` +
        `${chainDetailHtml}` +
        `${buildBreakdownRowHtml('locked', formatLockedUsd(context.lockedStablecoinUsd))}` +
        `<p class="poseidon-tooltip-body text-slate-200">Gas refill reserve is not active on this chain yet.</p>`
    );
}

export function buildGasRefillLockedTooltipHtml(context: GasRefillLockedTooltipContext): string {
    if (context.breakdown !== undefined) {
        return buildBreakdownTooltipHtml(context);
    }
    return buildFallbackTooltipHtml(context);
}

export function buildPortfolioLockedTooltipHtml(): string {
    return (
        `<p class="mb-2"><span class="poseidon-tooltip-title text-blue-200">locked</span></p>` +
        `<p class="poseidon-tooltip-body text-slate-200">${LOCKED_GUARDRAIL_LEAD_PARAGRAPH}</p>`
    );
}

export function buildWalletReserveTooltipHtml(): string {
    return (
        `<p class="mb-2"><span class="poseidon-tooltip-title text-blue-200">wallet reserve</span></p>` +
        `<p class="poseidon-tooltip-body text-slate-200">Native gas balances, stablecoin locked for gas refills, and recoverable on-chain wallet capital across enabled chains. Not part of deployable cash. Per-chain breakdown available in capital breakdown.</p>`
    );
}
