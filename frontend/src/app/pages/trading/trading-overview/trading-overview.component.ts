import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnDestroy, output, signal } from '@angular/core';
import { Tooltip } from 'primeng/tooltip';
import { DefiIconsService } from '../../../core/defi-icons.service';
import { BlockchainCashBalancePayload, TradingEquityCurvePointPayload, TradingPositionPayload } from '../../../core/models';
import { OptionalNumberPipe } from '../../../core/optional-number.pipe';
import { WebSocketService } from '../../../core/websocket.service';
import { SparklineComponent } from '../../../widgets/sparkline/sparkline.component';
import { PaperResetService } from '../../../widgets/paper-mode-control/paper-reset.service';
import { TradingPositionsTableComponent } from '../trading-positions-table/trading-positions-table.component';
import { TradingTradesTableComponent } from '../trading-trades-table/trading-trades-table.component';
import { firstNonNull, isNonNegative, mapNullable, safePercent } from './trading-overview.utils';
import {
    buildGasRefillLockedTooltipHtml,
    buildPortfolioLockedTooltipHtml,
    buildWalletReserveTooltipHtml
} from './trading-overview-gas-refill-locked-tooltip.builder';
import { TradingOverviewShadowingRegimeComponent } from './trading-overview-shadowing-regime/trading-overview-shadowing-regime.component';
import { buildSolanaRentTooltipHtml } from './trading-overview-solana-rent-tooltip.builder';

type LiquidityBalanceCard = BlockchainCashBalancePayload & { isPlaceholder: boolean };

@Component({
    standalone: true,
    selector: 'app-trading-overview',
    imports: [
        CommonModule,
        OptionalNumberPipe,
        TradingPositionsTableComponent,
        TradingTradesTableComponent,
        SparklineComponent,
        Tooltip,
        TradingOverviewShadowingRegimeComponent
    ],
    templateUrl: './trading-overview.component.html',
    styleUrl: './trading-overview.component.css'
})
export class TradingOverviewComponent implements OnDestroy {
    private readonly webSocketService = inject(WebSocketService);
    readonly liquidity = computed(() => this.webSocketService.tradingLiquidity());

    readonly blockchainBalances = computed<BlockchainCashBalancePayload[]>(
        () => this.liquidity()?.blockchain_balances ?? this.webSocketService.tradingPortfolio()?.blockchain_balances ?? []
    );

    readonly liquiditySymbol = computed(() => this.liquidity()?.stablecoin_currency_symbol ?? '$');

    readonly blockchainBalanceCards = computed<LiquidityBalanceCard[]>(() => {
        const balances = this.blockchainBalances();
        const cards: LiquidityBalanceCard[] = balances.map((balance) => ({
            ...balance,
            isPlaceholder: false
        }));

        const minimumCards = this.liquidity()?.maximum_chain_count ?? 4;
        const placeholdersMissing = Math.max(0, minimumCards - cards.length);
        for (let index = 0; index < placeholdersMissing; index++) {
            cards.push({
                blockchain_network: `placeholder_${index + 1}`,
                stablecoin_symbol: '--',
                stablecoin_address: '',
                wallet_address: '',
                stablecoin_currency_symbol: this.liquiditySymbol(),
                balance_raw: 0,
                native_token_symbol: '--',
                native_token_balance_raw: 0,
                native_token_balance_usd: 0,
                gas_refill_locked_stablecoin_usd: 0,
                isPlaceholder: true
            });
        }
        return cards;
    });

    readonly portfolio = computed(() => this.webSocketService.tradingPortfolio());

    readonly cash = computed<number | null>(() =>
        firstNonNull(
            mapNullable(this.liquidity(), (liquidity) => liquidity.available_cash_balance),
            mapNullable(this.portfolio(), (portfolio) => portfolio.deployable_cash_usd)
        )
    );

    readonly equity = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.total_equity_value));
    readonly realizedTotal = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_total));
    readonly unrealized = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.unrealized_profit_and_loss));

    readonly contributedCapitalBase = computed<number | null>(() => {
        const equity = this.equity();
        const realizedTotal = this.realizedTotal();
        const unrealized = this.unrealized();
        if (equity === null || realizedTotal === null || unrealized === null) {
            return null;
        }
        return equity - realizedTotal - unrealized;
    });

    readonly cumulativeSwapFees = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.cumulative_swap_fees_usd));
    readonly cumulativeSwapFeesPercent = computed<number | null>(() => {
        const fees = this.cumulativeSwapFees();
        const base = this.contributedCapitalBase();
        if (fees === null || base === null) {
            return null;
        }
        if (fees === 0) {
            return 0;
        }
        return safePercent(-Math.abs(fees), base);
    });

    readonly deployableCash = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.deployable_cash_usd));
    readonly holdings = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.holdings_mark_to_market_usd));
    readonly sizingCapital = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.sizing_capital_usd));

    readonly deployedPercentage = computed<number | null>(() => {
        const sizingCapital = this.sizingCapital();
        const holdings = this.holdings();
        if (sizingCapital === null || holdings === null) {
            return null;
        }
        if (sizingCapital <= 0) {
            return 0;
        }
        return Math.min(100, (holdings / sizingCapital) * 100);
    });

    readonly hasLiveBalances = computed(() => this.blockchainBalances().length > 0);
    readonly liquidityMode = computed(() => mapNullable(this.liquidity(), (liquidity) => liquidity.mode));

    readonly isPaperMode = computed(() => {
        const liquidityMode = this.liquidityMode();
        if (liquidityMode === 'PAPER') {
            return true;
        }
        if (liquidityMode === 'LIVE') {
            return false;
        }
        return this.blockchainBalances().some((balance) => balance.blockchain_network.trim().toLowerCase() === 'paper');
    });

    readonly isLiquiditySyncing = computed(() => !this.isPaperMode() && !this.hasLiveBalances());

    readonly displayChainCount = computed(() => {
        if (this.isPaperMode()) {
            return 1;
        }
        if (this.isLiquiditySyncing()) {
            return 0;
        }
        return this.blockchainBalances().length;
    });

    readonly positions = computed<TradingPositionPayload[]>(() => this.webSocketService.tradingPositions());
    readonly openPositionCount = computed(() => this.positions().length);

    readonly displayOpenPositionCount = computed<string | number>(() => {
        if (this.portfolio() === null || this.portfolio() === undefined) {
            return '—';
        }
        return this.openPositionCount();
    });

    readonly displaySlotCount = computed(() => this.liquidity()?.maximum_chain_count ?? 4);
    readonly equitySpark = computed<TradingEquityCurvePointPayload[]>(() => this.portfolio()?.equity_curve ?? []);
    readonly isNonNegative = isNonNegative;
    readonly paperResetService = inject(PaperResetService);
    readonly isPaperResetInProgress = this.paperResetService.isResetInProgress;
    readonly liquiditySkeletonSlotIndices = computed(() => this.rangeArray(this.displaySlotCount()));
    readonly liquiditySubtitle = computed(() => 'deployable');
    readonly liquidityTitle = computed(() => 'capital breakdown');
    readonly nowMilliseconds = signal(Date.now());

    readonly liquidityUpdatedAgo = computed(() => {
        if (this.isPaperMode()) {
            return '—';
        }
        if (this.isLiquiditySyncing()) {
            return '—';
        }
        const updatedAt = this.liquidity()?.updated_at;
        if (!updatedAt) {
            return '--';
        }
        const updatedAtMilliseconds = Date.parse(updatedAt);
        if (!Number.isFinite(updatedAtMilliseconds)) {
            return '--';
        }
        const elapsedSeconds = Math.max(0, Math.floor((this.nowMilliseconds() - updatedAtMilliseconds) / 1000));
        if (elapsedSeconds < 60) {
            return `${elapsedSeconds}s ago`;
        }
        const elapsedMinutes = Math.floor(elapsedSeconds / 60);
        if (elapsedMinutes < 60) {
            return `${elapsedMinutes}m ago`;
        }
        const elapsedHours = Math.floor(elapsedMinutes / 60);
        return `${elapsedHours}h ago`;
    });

    readonly openHoldingsCostBasis = computed<number | null>(() => {
        const holdings = this.holdings();
        const unrealized = this.unrealized();
        if (holdings === null || unrealized === null) {
            return null;
        }
        return holdings - unrealized;
    });

    readonly openShadowChronicle = output<void>();
    readonly portfolioLockedTooltipHtml = computed(() => buildPortfolioLockedTooltipHtml());
    readonly realized24h = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_24h));
    readonly realized24hPercent = computed<number | null>(() => safePercent(this.realized24h(), this.contributedCapitalBase()));
    readonly realized30d = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_30d));
    readonly realized30dPercent = computed<number | null>(() => safePercent(this.realized30d(), this.contributedCapitalBase()));
    readonly realized7d = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_7d));
    readonly realized7dPercent = computed<number | null>(() => safePercent(this.realized7d(), this.contributedCapitalBase()));
    readonly realizedTotalPercent = computed<number | null>(() => safePercent(this.realizedTotal(), this.contributedCapitalBase()));

    readonly sizingBaseTooltipHtml =
        `<p class="mb-2"><span class="poseidon-tooltip-title text-blue-200">sizing base</span></p>` +
        `<p class="poseidon-tooltip-body text-slate-200">Deployable cash plus open holdings at mark-to-market. Used by the bot for per-buy sizing. Excludes wallet reserve</p>`;

    readonly swapFeesTooltipHtml =
        `<p class="poseidon-tooltip-body text-slate-200">Cumulative swap fees paid on trades. Deducted from unrealized on open positions and from realized on closed sells.</p>`;

    readonly totalGasRefillLockedStablecoin = computed<number | null>(() =>
        mapNullable(this.portfolio(), (portfolio) => portfolio.total_gas_refill_locked_stablecoin_usd)
    );

    readonly unrealizedPercent = computed<number | null>(() => safePercent(this.unrealized(), this.openHoldingsCostBasis()));
    readonly walletReserve = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.wallet_auxiliary_assets_usd));
    readonly walletReserveTooltipHtml = buildWalletReserveTooltipHtml();

    private readonly chainIconCandidateIndices = new Map<string, number>();
    private readonly defiIconsService = inject(DefiIconsService);
    private readonly nowRefreshInterval = window.setInterval(() => this.nowMilliseconds.set(Date.now()), 1000);

    ngOnDestroy(): void {
        window.clearInterval(this.nowRefreshInterval);
    }

    buildGasRefillLockedTooltip(balance: LiquidityBalanceCard): string {
        return buildGasRefillLockedTooltipHtml({
            nativeTokenSymbol: balance.native_token_symbol,
            isPaperMode: this.isPaperMode(),
            lockedStablecoinUsd: balance.gas_refill_locked_stablecoin_usd,
            breakdown: balance.gas_refill_locked_breakdown,
            gasRefillBudgetDetailScope: balance.gas_refill_budget_detail_scope
        });
    }

    buildSolanaRentTooltip(balance: LiquidityBalanceCard): string {
        if (!this.isSolanaBalanceCard(balance)) {
            return '';
        }
        const rentBreakdown = balance.solana_token_account_rent;
        if (rentBreakdown === undefined) {
            return '';
        }
        return buildSolanaRentTooltipHtml({
            stablecoinSymbol: balance.stablecoin_symbol,
            lockedSol: rentBreakdown.locked_sol,
            totalUsd: rentBreakdown.active_usd + rentBreakdown.closable_usd,
            activeAccountCount: rentBreakdown.active_account_count,
            activeUsd: rentBreakdown.active_usd,
            closableAccountCount: rentBreakdown.closable_account_count,
            closableUsd: rentBreakdown.closable_usd,
            pendingReclaimAccountCount: rentBreakdown.pending_reclaim_account_count,
            pendingReclaimUsd: rentBreakdown.pending_reclaim_usd
        });
    }

    buildWalletAddressTooltip(balance: LiquidityBalanceCard): string {
        return (
            `<p class="mb-1"><span class="poseidon-tooltip-title text-cyan-200">wallet address</span></p>` +
            `<p class="font-mono text-[10px] text-slate-200 break-all">${balance.wallet_address}</p>`
        );
    }

    formatFeesPercentInline(value: number | null): string {
        if (value === null || !Number.isFinite(value)) {
            return '';
        }
        return `(-${Math.abs(value).toFixed(2)}%)`;
    }

    formatPercentInline(value: number | null): string {
        if (value === null || !Number.isFinite(value)) {
            return '';
        }
        const sign = value > 0 ? '+' : '';
        return `(${sign}${value.toFixed(2)}%)`;
    }

    handleChainIconError(blockchainNetwork: string, event: Event): void {
        const imageElement = event.target as HTMLImageElement | null;
        if (!imageElement) {
            return;
        }
        const normalizedNetwork = blockchainNetwork.trim().toLowerCase();
        const candidates = this.defiIconsService.getChainIconCandidates(normalizedNetwork);
        const nextIndex = (this.chainIconCandidateIndices.get(normalizedNetwork) ?? 0) + 1;
        this.chainIconCandidateIndices.set(normalizedNetwork, nextIndex);
        const nextCandidate = candidates[nextIndex];
        if (nextCandidate) {
            imageElement.src = nextCandidate;
            return;
        }
        imageElement.style.display = 'none';
    }

    isPaperBalanceCard(balance: LiquidityBalanceCard): boolean {
        return balance.blockchain_network.trim().toLowerCase() === 'paper';
    }

    isSolanaBalanceCard(balance: LiquidityBalanceCard): boolean {
        return balance.blockchain_network.trim().toLowerCase() === 'solana';
    }

    pnlValueClass(value: number | null): string {
        if (value === null) {
            return '';
        }
        return isNonNegative(value) ? '!text-emerald-400' : '!text-red-400';
    }

    rangeArray(length: number): number[] {
        return Array.from({ length }, (_, index) => index);
    }

    resetPaperPortfolio(): void {
        this.paperResetService.resetPaperPortfolio();
    }

    resolveChainIconUrl(blockchainNetwork: string): string {
        const normalizedNetwork = blockchainNetwork.trim().toLowerCase();
        const candidates = this.defiIconsService.getChainIconCandidates(normalizedNetwork);
        const candidateIndex = this.chainIconCandidateIndices.get(normalizedNetwork) ?? 0;
        return candidates[candidateIndex] ?? candidates[0] ?? '';
    }

    resolveSolanaRentLockedSol(balance: LiquidityBalanceCard): number {
        return balance.solana_token_account_rent?.locked_sol ?? 0;
    }

    resolveSolanaRentTotalUsd(balance: LiquidityBalanceCard): number {
        const rentBreakdown = balance.solana_token_account_rent;
        if (rentBreakdown === undefined) {
            return 0;
        }
        return rentBreakdown.active_usd + rentBreakdown.closable_usd;
    }

    resolveWalletAddressDisplay(balance: LiquidityBalanceCard): string {
        return balance.wallet_address;
    }

    shouldShowGasMetricEmDash(balance: LiquidityBalanceCard): boolean {
        return balance.isPlaceholder || this.isPaperBalanceCard(balance);
    }

    shouldShowLockedMetricEmDash(balance: LiquidityBalanceCard): boolean {
        return balance.isPlaceholder || this.isPaperBalanceCard(balance);
    }

    shouldShowRentMetricEmDash(balance: LiquidityBalanceCard): boolean {
        return balance.isPlaceholder || this.isPaperBalanceCard(balance) || !this.isSolanaBalanceCard(balance);
    }
}
