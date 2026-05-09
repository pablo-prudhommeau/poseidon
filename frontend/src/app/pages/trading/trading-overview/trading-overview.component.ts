import {Component, computed, inject} from '@angular/core';
import {CommonModule} from '@angular/common';
import {WebSocketService} from '../../../core/websocket.service';
import {BlockchainCashBalancePayload, TradingEquityCurvePointPayload, TradingPositionPayload} from '../../../core/models';
import {OptionalNumberPipe} from '../../../core/optional-number.pipe';
import {TradingPositionsTableComponent} from '../trading-positions-table/trading-positions-table.component';
import {TradingTradesTableComponent} from '../trading-trades-table/trading-trades-table.component';
import {SparklineComponent} from '../../../widgets/sparkline/sparkline.component';

type LiquidityBalanceCard = BlockchainCashBalancePayload & { isPlaceholder: boolean };

@Component({
    standalone: true,
    selector: 'app-trading-overview',
    imports: [CommonModule, OptionalNumberPipe, TradingPositionsTableComponent, TradingTradesTableComponent, SparklineComponent],
    templateUrl: './trading-overview.component.html',
    styleUrl: './trading-overview.component.css'
})
export class TradingOverviewComponent {
    private readonly webSocketService = inject(WebSocketService);

    readonly portfolio = computed(() => this.webSocketService.portfolio());
    readonly equity = computed<number | null>(() => this.mapNullable(this.portfolio(), portfolio => portfolio.total_equity_value));
    readonly liquidity = computed(() => this.webSocketService.liquidity());
    readonly cash = computed<number | null>(() => this.firstNonNull(
        this.mapNullable(this.liquidity(), liquidity => liquidity.available_cash_balance),
        this.mapNullable(this.portfolio(), portfolio => portfolio.available_cash_balance)
    ));
    readonly holdings = computed<number | null>(() => this.mapNullable(this.portfolio(), portfolio => portfolio.active_holdings_value));
    readonly unrealized = computed<number | null>(() => this.mapNullable(this.portfolio(), portfolio => portfolio.unrealized_profit_and_loss));
    readonly realizedTotal = computed<number | null>(() => this.mapNullable(this.portfolio(), portfolio => portfolio.realized_profit_and_loss_total));
    readonly realized24h = computed<number | null>(() => this.mapNullable(this.portfolio(), portfolio => portfolio.realized_profit_and_loss_24h));
    readonly equitySpark = computed<TradingEquityCurvePointPayload[]>(() => this.portfolio()?.equity_curve ?? []);

    readonly shadowStatus = computed(() => this.portfolio()?.shadow_intelligence_status);
    readonly shadowPhase = computed(() => this.shadowStatus()?.phase ?? 'DISABLED');
    readonly shadowOutcomeProgress = computed(() => this.shadowStatus()?.outcome_progress_percentage ?? 0);
    readonly shadowHoursProgress = computed(() => this.shadowStatus()?.hours_progress_percentage ?? 0);
    readonly shadowResolvedCount = computed(() => this.shadowStatus()?.resolved_outcome_count ?? 0);
    readonly shadowRequiredCount = computed(() => this.shadowStatus()?.required_outcome_count ?? 0);
    readonly shadowElapsedHours = computed(() => this.shadowStatus()?.elapsed_hours ?? 0);
    readonly shadowRequiredHours = computed(() => this.shadowStatus()?.required_hours ?? 0);

    readonly shadowMeta = computed(() => this.webSocketService.shadowMeta());
    readonly shadowProfitFactor = computed<number | null>(() => this.mapNullable(this.shadowMeta(), shadowMeta => shadowMeta.profit_factor));
    readonly shadowMinimumProfitFactor = computed<number | null>(() => this.mapNullable(this.shadowMeta(), shadowMeta => shadowMeta.minimum_profit_factor));
    readonly shadowWinRate = computed<number | null>(() => this.mapNullable(this.shadowMeta(), shadowMeta => shadowMeta.win_rate_percentage));
    readonly shadowExpectedValue = computed<number | null>(() => this.mapNullable(this.shadowMeta(), shadowMeta => shadowMeta.expected_value_usd));
    readonly shadowCapitalVelocity = computed<number | null>(() => this.mapNullable(this.shadowMeta(), shadowMeta => shadowMeta.capital_velocity));
    readonly shadowTradable = computed(() => {
        const shadowProfitFactor = this.shadowProfitFactor();
        const shadowMinimumProfitFactor = this.shadowMinimumProfitFactor();
        if (this.shadowPhase() !== 'ACTIVE' || shadowProfitFactor === null || shadowMinimumProfitFactor === null) {
            return false;
        }
        return shadowProfitFactor >= shadowMinimumProfitFactor;
    });
    readonly shadowProfitFactorProgress = computed(() => {
        const minimumProfitFactor = this.shadowMinimumProfitFactor();
        const shadowProfitFactor = this.shadowProfitFactor();
        if (minimumProfitFactor === null || shadowProfitFactor === null || minimumProfitFactor <= 0) {
            return 0;
        }
        return Math.min(100, (shadowProfitFactor / minimumProfitFactor) * 100);
    });

    readonly blockchainBalances = computed<BlockchainCashBalancePayload[]>(() => this.liquidity()?.blockchain_balances ?? this.webSocketService.portfolio()?.blockchain_balances ?? []);
    readonly liquidityMode = computed(() => this.mapNullable(this.liquidity(), liquidity => liquidity.mode));
    readonly hasLiveBalances = computed(() => this.blockchainBalances().length > 0);
    readonly shouldShowReserveModeCard = computed(() => this.liquidityMode() === 'PAPER');
    readonly shouldShowLiquiditySyncCard = computed(() => !this.hasLiveBalances() && !this.shouldShowReserveModeCard());
    readonly blockchainBalanceCards = computed<LiquidityBalanceCard[]>(() => {
        const balances = this.blockchainBalances();
        const cards: LiquidityBalanceCard[] = balances.map(balance => ({
            ...balance,
            isPlaceholder: false,
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
                isPlaceholder: true,
            });
        }
        return cards;
    });
    readonly liveChainCount = computed(() => this.blockchainBalances().length);
    readonly liveSlotCount = computed(() => this.liquidity()?.mode === 'LIVE' ? (this.liquidity()?.maximum_chain_count ?? 4) : this.blockchainBalances().length);

    readonly positions = computed<TradingPositionPayload[]>(() => this.webSocketService.positions());
    readonly openPositionCount = computed(() => this.positions().filter(position => position.position_phase === 'OPEN' || position.position_phase === 'PARTIAL').length);

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

    readonly chainIcons: Record<string, string> = {
        'solana': 'fa-bolt',
        'ethereum': 'fa-diamond',
        'bsc': 'fa-gem',
        'base': 'fa-cube',
        'avalanche': 'fa-snowflake',
    };

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

    readonly liquiditySymbol = computed(() => this.liquidity()?.stablecoin_currency_symbol ?? '$');

    readonly shadowRegimeLabel = computed(() => {
        if (this.shadowPhase() === 'DISABLED') {
            return 'disabled';
        }
        if (this.shadowPhase() === 'LEARNING') {
            return 'learning';
        }
        if (this.shadowPhase() === 'ACTIVE' && (this.shadowProfitFactor() === null || this.shadowMinimumProfitFactor() === null)) {
            return 'syncing';
        }
        return this.shadowTradable() ? 'tradable' : 'bear meta';
    });

    readonly shadowRegimeClasses = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'bg-purple-500/10 text-purple-300 border-purple-500/20';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'bg-red-500/10 text-red-300 border-red-500/20';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'bg-amber-500/10 text-amber-300 border-amber-500/20';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'bg-purple-500/10 text-purple-300 border-purple-500/20';
        }
        return 'bg-slate-500/10 text-slate-300 border-slate-500/20';
    });

    readonly shadowTitleTextClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'text-purple-300';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'text-red-300';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'text-amber-300';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'text-purple-300';
        }
        return 'text-slate-300';
    });

    readonly shadowAccentTextClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'text-purple-400';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'text-red-400';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'text-amber-400';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'text-purple-400';
        }
        return 'text-slate-400';
    });

    readonly shadowProgressClass = computed(() => {
        if (this.shadowRegimeLabel() === 'tradable') {
            return 'bg-purple-400';
        }
        if (this.shadowRegimeLabel() === 'bear meta') {
            return 'bg-red-400';
        }
        if (this.shadowRegimeLabel() === 'learning') {
            return 'bg-amber-400';
        }
        if (this.shadowRegimeLabel() === 'syncing') {
            return 'bg-purple-400';
        }
        return 'bg-slate-400';
    });

    formatMultiplier(value: number | null): string {
        if (value === null) {
            return '—';
        }
        if (value >= 900) {
            return '999+';
        }
        return value.toFixed(2);
    }

    isNonNegative(value: number | null): boolean {
        if (value === null) {
            return false;
        }
        return value >= 0;
    }

    private mapNullable<TSource, TProjected>(value: TSource | null, mapper: (value: TSource) => TProjected): TProjected | null {
        if (value === null) {
            return null;
        }
        return mapper(value);
    }

    private firstNonNull(...values: Array<number | null>): number | null {
        for (const value of values) {
            if (value !== null) {
                return value;
            }
        }
        return null;
    }

    rangeArray(length: number): number[] {
        return Array.from({length}, (_, index) => index);
    }
}