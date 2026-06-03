import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnDestroy, output, signal } from '@angular/core';
import { Tooltip } from 'primeng/tooltip';
import { BlockchainCashBalancePayload, TradingEquityCurvePointPayload, TradingPositionPayload } from '../../../core/models';
import { OptionalNumberPipe } from '../../../core/optional-number.pipe';
import { WebSocketService } from '../../../core/websocket.service';
import { SparklineComponent } from '../../../widgets/sparkline/sparkline.component';
import { TradingPositionsTableComponent } from '../trading-positions-table/trading-positions-table.component';
import { TradingTradesTableComponent } from '../trading-trades-table/trading-trades-table.component';
import { firstNonNull, isNonNegative, mapNullable } from './trading-overview.utils';
import { buildSolanaRentTooltipHtml } from './trading-overview-solana-rent-tooltip.builder';
import { TradingOverviewShadowingRegimeComponent } from './trading-overview-shadowing-regime/trading-overview-shadowing-regime.component';

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

        if (this.liquidity()?.mode !== 'LIVE') {
            return cards;
        }

        const minimumCards = this.liquidity()?.maximum_chain_count ?? 4;
        const placeholdersMissing = Math.max(0, minimumCards - cards.length);
        for (let index = 0; index < placeholdersMissing; index++) {
            cards.push({
                blockchain_network: `placeholder_${index + 1}`,
                stablecoin_symbol: '--',
                stablecoin_address: '',
                stablecoin_currency_symbol: this.liquiditySymbol(),
                balance_raw: 0,
                native_token_symbol: '--',
                native_token_balance_raw: 0,
                native_token_balance_usd: 0,
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

    readonly chainIcons: Record<string, string> = {
        solana: 'fa-bolt',
        ethereum: 'fa-diamond',
        bsc: 'fa-gem',
        base: 'fa-cube',
        avalanche: 'fa-snowflake'
    };

    readonly cumulativeSwapFees = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.cumulative_swap_fees_usd));
    readonly deployableCash = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.deployable_cash_usd));
    readonly equity = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.total_equity_value));
    readonly holdings = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.holdings_mark_to_market_usd));
    readonly deployedPercentage = computed<number | null>(() => {
        const totalEquity = this.equity();
        const holdings = this.holdings();
        if (totalEquity === null || holdings === null) {
            return null;
        }
        if (totalEquity <= 0) {
            return 0;
        }
        return Math.min(100, (holdings / totalEquity) * 100);
    });
    readonly equitySpark = computed<TradingEquityCurvePointPayload[]>(() => this.portfolio()?.equity_curve ?? []);

    readonly hasLiveBalances = computed(() => this.blockchainBalances().length > 0);

    readonly isNonNegative = isNonNegative;

    readonly liquidityMode = computed(() => mapNullable(this.liquidity(), (liquidity) => liquidity.mode));

    readonly isPaperMode = computed(() => this.liquidityMode() === 'PAPER');

    readonly liquiditySubtitle = computed(() => {
        if (this.liquidityMode() === 'LIVE') {
            return 'deployable stablecoin';
        }
        if (this.liquidityMode() === null) {
            return 'awaiting liquidity mode';
        }
        return 'available trading reserve';
    });
    readonly liquidityTitle = computed(() => {
        const liquidityMode = this.liquidityMode();
        if (liquidityMode === 'LIVE') {
            return 'on-chain liquidity';
        }
        if (liquidityMode === 'PAPER') {
            return 'paper reserve';
        }
        return 'reserve snapshot';
    });
    private readonly nowMilliseconds = signal(Date.now());
    readonly liquidityUpdatedAgo = computed(() => {
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

    readonly liveChainCount = computed(() => this.blockchainBalances().length);

    readonly liveSlotCount = computed(() =>
        this.liquidity()?.mode === 'LIVE' ? (this.liquidity()?.maximum_chain_count ?? 4) : this.blockchainBalances().length
    );

    readonly positions = computed<TradingPositionPayload[]>(() => this.webSocketService.tradingPositions());

    readonly openPositionCount = computed(() => this.positions().length);

    readonly openShadowChronicle = output<void>();

    readonly primaryStablecoinSymbol = computed(() => {
        const balance = this.blockchainBalances()[0];
        const symbol = balance?.stablecoin_symbol?.trim();
        return symbol && symbol.length > 0 ? symbol : 'stablecoin';
    });

    readonly realized24h = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_24h));

    readonly realized30d = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_30d));

    readonly realized7d = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_7d));

    readonly realizedTotal = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_total));

    readonly shouldShowReserveModeCard = computed(() => this.liquidityMode() === 'PAPER');
    readonly shouldShowLiquiditySyncCard = computed(() => !this.hasLiveBalances() && !this.shouldShowReserveModeCard());
    readonly sizingBaseTooltipHtml =
        `<p class="mb-2"><span class="poseidon-tooltip-title text-blue-200">sizing base</span></p>` +
        `<p class="poseidon-tooltip-body text-slate-200">Deployable cash plus open holdings at mark-to-market. Used by the bot for per-buy sizing. Excludes wallet reserve</p>`;
    readonly sizingCapital = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.sizing_capital_usd));
    readonly swapFeesTooltipHtml = `<p class="poseidon-tooltip-body text-slate-200">Cumulative swap fees on trades</p>`;
    readonly unrealized = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.unrealized_profit_and_loss));

    readonly walletReserve = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.wallet_auxiliary_assets_usd));

    readonly walletReserveTooltipHtml = computed(() => {
        const stablecoinSymbol = this.primaryStablecoinSymbol();
        return (
            `<p class="mb-2"><span class="poseidon-tooltip-title text-blue-200">wallet reserve</span></p>` +
            `<p class="poseidon-tooltip-body text-slate-200">Native gas plus Solana ATA rent locked in the wallet (recoverable). Not part of deployable ${stablecoinSymbol}</p>`
        );
    });

    private readonly nowRefreshInterval = window.setInterval(() => this.nowMilliseconds.set(Date.now()), 1000);

    ngOnDestroy(): void {
        window.clearInterval(this.nowRefreshInterval);
    }

    buildSolanaRentTooltip(balance: LiquidityBalanceCard): string {
        const rentBreakdown = balance.solana_token_account_rent;
        const rentTotalUsd = this.resolveSolanaRentTotalUsd(balance);
        const rentLockedSol = this.resolveSolanaRentLockedSol(balance);
        if (!rentBreakdown || rentTotalUsd === null || rentLockedSol === null) {
            return '';
        }
        return buildSolanaRentTooltipHtml({
            stablecoinSymbol: balance.stablecoin_symbol,
            lockedSol: rentLockedSol,
            totalUsd: rentTotalUsd,
            activeAccountCount: rentBreakdown.active_account_count,
            activeUsd: rentBreakdown.active_usd,
            closableAccountCount: rentBreakdown.closable_account_count,
            closableUsd: rentBreakdown.closable_usd,
            pendingReclaimAccountCount: rentBreakdown.pending_reclaim_account_count,
            pendingReclaimUsd: rentBreakdown.pending_reclaim_usd
        });
    }

    buildStablecoinAddressTooltip(address: string): string {
        return (
            `<p class="mb-1"><span class="poseidon-tooltip-title text-cyan-200">mint address</span></p>` +
            `<p class="font-mono text-[10px] text-slate-200 break-all">${address}</p>`
        );
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

    resolveSolanaRentLockedSol(balance: LiquidityBalanceCard): number | null {
        const rentBreakdown = balance.solana_token_account_rent;
        if (!rentBreakdown) {
            return null;
        }
        return rentBreakdown.locked_sol;
    }

    resolveSolanaRentTotalUsd(balance: LiquidityBalanceCard): number | null {
        const rentBreakdown = balance.solana_token_account_rent;
        if (!rentBreakdown) {
            return null;
        }
        return rentBreakdown.active_usd + rentBreakdown.closable_usd;
    }
}
