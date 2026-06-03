export interface SolanaRentTooltipContext {
    stablecoinSymbol: string;
    lockedSol: number;
    totalUsd: number;
    activeAccountCount: number;
    activeUsd: number;
    closableAccountCount: number;
    closableUsd: number;
    pendingReclaimAccountCount: number;
    pendingReclaimUsd: number;
}

function resolveSolPerAccount(context: SolanaRentTooltipContext): number {
    const trackedAccountCount = context.activeAccountCount + context.closableAccountCount;
    if (trackedAccountCount === 0) {
        return 0;
    }
    return context.lockedSol / trackedAccountCount;
}

function formatAccountsQualifier(accountCount: number): string {
    const noun = accountCount === 1 ? 'account' : 'accounts';
    return `<span class="poseidon-tooltip-muted">${accountCount} ${noun}</span>`;
}

function formatRentAmount(sol: number, usd: number): string {
    return `<span class="tabular-nums">${sol.toFixed(4)} SOL ($ ${usd.toFixed(2)})</span>`;
}

function formatRentRowValue(accountCount: number, sol: number, usd: number): string {
    return (
        `<span class="inline-flex items-center justify-end gap-1.5 whitespace-nowrap">` +
        `${formatAccountsQualifier(accountCount)}` +
        `<span class="poseidon-tooltip-rent-separator" aria-hidden="true">·</span>` +
        `${formatRentAmount(sol, usd)}` +
        `</span>`
    );
}

function buildRentBreakdownRowHtml(label: string, valueHtml: string): string {
    return (
        `<p class="poseidon-tooltip-body mb-1.5 flex items-baseline justify-between gap-4 text-slate-200">` +
        `<span class="poseidon-tooltip-label shrink-0">${label}</span>` +
        `${valueHtml}` +
        `</p>`
    );
}

export function buildSolanaRentTooltipHtml(context: SolanaRentTooltipContext): string {
    const solPerAccount = resolveSolPerAccount(context);
    const lockedAccountCount = context.activeAccountCount + context.closableAccountCount;
    const lockedValue = formatRentRowValue(lockedAccountCount, context.lockedSol, context.totalUsd);
    const activeSol = context.activeAccountCount * solPerAccount;
    const closableSol = context.closableAccountCount * solPerAccount;
    const pendingSol = context.pendingReclaimAccountCount * solPerAccount;
    const activeValue = formatRentRowValue(context.activeAccountCount, activeSol, context.activeUsd);
    const closableValue = formatRentRowValue(context.closableAccountCount, closableSol, context.closableUsd);
    const pendingValue = formatRentRowValue(context.pendingReclaimAccountCount, pendingSol, context.pendingReclaimUsd);

    return (
        `<p class="mb-2"><span class="poseidon-tooltip-title text-cyan-200">ata rent</span></p>` +
        `<p class="poseidon-tooltip-body mb-3 text-slate-200">Rent-exempt minimum balance on SPL token accounts. ${context.stablecoinSymbol} stablecoin ATA is excluded.</p>` +
        `${buildRentBreakdownRowHtml('locked', lockedValue)}` +
        `${buildRentBreakdownRowHtml('active accounts', activeValue)}` +
        `${buildRentBreakdownRowHtml('closable now', closableValue)}` +
        `${buildRentBreakdownRowHtml('pending reclaim', pendingValue)}`
    );
}
