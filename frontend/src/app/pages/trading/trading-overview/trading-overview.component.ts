import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnDestroy, output, signal } from '@angular/core';
import { BlockchainCashBalancePayload, TradingEquityCurvePointPayload, TradingPositionPayload } from '../../../core/models';
import { OptionalNumberPipe } from '../../../core/optional-number.pipe';
import { WebSocketService } from '../../../core/websocket.service';
import { SparklineComponent } from '../../../widgets/sparkline/sparkline.component';
import { TradingPositionsTableComponent } from '../trading-positions-table/trading-positions-table.component';
import { TradingTradesTableComponent } from '../trading-trades-table/trading-trades-table.component';
import { firstNonNull, isNonNegative, mapNullable } from './trading-overview.utils';
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
            mapNullable(this.portfolio(), (portfolio) => portfolio.available_cash_balance)
        )
    );

    readonly chainIcons: Record<string, string> = {
        solana: 'fa-bolt',
        ethereum: 'fa-diamond',
        bsc: 'fa-gem',
        base: 'fa-cube',
        avalanche: 'fa-snowflake'
    };

    readonly equity = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.total_equity_value));
    readonly holdings = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.active_holdings_value));

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

    readonly liquiditySubtitle = computed(() => {
        const balances = this.blockchainBalances();
        if (balances.length > 0) {
            return `${balances[0].stablecoin_symbol} across ${balances.length} chain(s)`;
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

    readonly openPositionCount = computed(
        () => this.positions().filter((position) => position.position_phase === 'OPEN' || position.position_phase === 'PARTIAL').length
    );

    readonly openShadowChronicle = output<void>();
    readonly realized24h = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_24h));
    readonly realizedTotal = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_total));
    readonly shouldShowReserveModeCard = computed(() => this.liquidityMode() === 'PAPER');
    readonly shouldShowLiquiditySyncCard = computed(() => !this.hasLiveBalances() && !this.shouldShowReserveModeCard());
    readonly unrealized = computed<number | null>(() => mapNullable(this.portfolio(), (portfolio) => portfolio.unrealized_profit_and_loss));

    private readonly nowRefreshInterval = window.setInterval(() => this.nowMilliseconds.set(Date.now()), 1000);

    ngOnDestroy(): void {
        window.clearInterval(this.nowRefreshInterval);
    }

    rangeArray(length: number): number[] {
        return Array.from({ length }, (_, index) => index);
    }
}
