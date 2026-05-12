import { CommonModule } from '@angular/common';
import { Component, computed, inject, output } from '@angular/core';
import { BlockchainCashBalancePayload, TradingEquityCurvePointPayload, TradingPositionPayload } from '../../../core/models';
import { OptionalNumberPipe } from '../../../core/optional-number.pipe';
import { WebSocketService } from '../../../core/websocket.service';
import { SparklineComponent } from '../../../widgets/sparkline/sparkline.component';
import { TradingPositionsTableComponent } from '../trading-positions-table/trading-positions-table.component';
import { TradingTradesTableComponent } from '../trading-trades-table/trading-trades-table.component';

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

    readonly liquidity = computed(() => this.webSocketService.liquidity());

    readonly blockchainBalances = computed<BlockchainCashBalancePayload[]>(
        () => this.liquidity()?.blockchain_balances ?? this.webSocketService.portfolio()?.blockchain_balances ?? []
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
    readonly portfolio = computed(() => this.webSocketService.portfolio());

    readonly cash = computed<number | null>(() =>
        this.firstNonNull(
            this.mapNullable(this.liquidity(), (liquidity) => liquidity.available_cash_balance),
            this.mapNullable(this.portfolio(), (portfolio) => portfolio.available_cash_balance)
        )
    );
    readonly chainIcons: Record<string, string> = {
        solana: 'fa-bolt',
        ethereum: 'fa-diamond',
        bsc: 'fa-gem',
        base: 'fa-cube',
        avalanche: 'fa-snowflake'
    };
    readonly equity = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.total_equity_value));
    readonly holdings = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.active_holdings_value));
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
    readonly liquidityMode = computed(() => this.mapNullable(this.liquidity(), (liquidity) => liquidity.mode));
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
    readonly liveChainCount = computed(() => this.blockchainBalances().length);
    readonly liveSlotCount = computed(() =>
        this.liquidity()?.mode === 'LIVE' ? (this.liquidity()?.maximum_chain_count ?? 4) : this.blockchainBalances().length
    );
    readonly positions = computed<TradingPositionPayload[]>(() => this.webSocketService.positions());

    readonly openPositionCount = computed(
        () => this.positions().filter((position) => position.position_phase === 'OPEN' || position.position_phase === 'PARTIAL').length
    );
    readonly openShadowChronicle = output<void>();
    readonly realized24h = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_24h));
    readonly realizedTotal = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.realized_profit_and_loss_total));
    readonly shadowMeta = computed(() => this.webSocketService.shadowMeta());
    readonly shadowChronicleProfitFactor = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.chronicle_profit_factor)
    );
    readonly shadowChronicleProfitFactorThreshold = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.chronicle_profit_factor_threshold)
    );
    readonly shadowEmpiricalProfitFactor = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.empirical_profit_factor)
    );
    readonly shadowEmpiricalProfitFactorThreshold = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.empirical_profit_factor_threshold)
    );

    readonly shadowStatus = computed(() => this.portfolio()?.shadow_intelligence_status);

    readonly shadowPhase = computed(() => this.shadowStatus()?.phase ?? 'DISABLED');

    readonly shadowSparseExpectedValueUsd = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.sparse_expected_value_usd)
    );
    readonly shadowSparseExpectedValueUsdThreshold = computed<number | null>(() =>
        this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.sparse_expected_value_usd_threshold)
    );

    readonly shadowTradable = computed(() => {
        const empiricalPf = this.shadowEmpiricalProfitFactor();
        const empiricalThreshold = this.shadowEmpiricalProfitFactorThreshold();
        const chroniclePf = this.shadowChronicleProfitFactor();
        const chronicleThreshold = this.shadowChronicleProfitFactorThreshold();
        const sparseEv = this.shadowSparseExpectedValueUsd();
        const sparseEvThreshold = this.shadowSparseExpectedValueUsdThreshold();

        if (
            this.shadowPhase() !== 'ACTIVE' ||
            empiricalPf === null ||
            empiricalThreshold === null ||
            chroniclePf === null ||
            chronicleThreshold === null ||
            sparseEv === null ||
            sparseEvThreshold === null
        ) {
            return false;
        }
        return empiricalPf >= empiricalThreshold && chroniclePf >= chronicleThreshold && sparseEv >= sparseEvThreshold;
    });

    readonly shadowRegimeLabel = computed(() => {
        if (this.shadowPhase() === 'DISABLED') {
            return 'disabled';
        }
        if (this.shadowPhase() === 'LEARNING') {
            return 'learning';
        }
        if (
            this.shadowPhase() === 'ACTIVE' &&
            (this.shadowEmpiricalProfitFactor() === null ||
                this.shadowEmpiricalProfitFactorThreshold() === null ||
                this.shadowChronicleProfitFactor() === null ||
                this.shadowChronicleProfitFactorThreshold() === null ||
                this.shadowSparseExpectedValueUsd() === null ||
                this.shadowSparseExpectedValueUsdThreshold() === null)
        ) {
            return 'syncing';
        }
        return this.shadowTradable() ? 'tradable' : 'bear meta';
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

    readonly shadowCapitalVelocity = computed<number | null>(() => this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.capital_velocity));

    readonly shadowChronicleGeometryLabel = computed(() => {
        const meta = this.shadowMeta();
        if (!meta) {
            return '—';
        }
        return `momentum ${this.formatShadowMetricLookbackDays(meta.chronicle_profit_factor_lookback_days)}d ${meta.chronicle_profit_factor_bucket_width_seconds}s p${meta.chronicle_profit_factor_moving_average_period}`;
    });
    readonly shadowChronicleProfitFactorProgress = computed(() => {
        const threshold = this.shadowChronicleProfitFactorThreshold();
        const value = this.shadowChronicleProfitFactor();
        if (threshold === null || value === null || threshold <= 0) {
            return null;
        }
        return Math.min(100, (value / threshold) * 100);
    });
    readonly shadowElapsedHours = computed(() => this.shadowStatus()?.elapsed_hours ?? 0);
    readonly shadowEmpiricalGeometryLabel = computed(() => {
        const meta = this.shadowMeta();
        if (!meta) {
            return '—';
        }
        return `empirical, ${this.formatShadowVerdictWindowToken(meta.empirical_profit_factor_window_verdict_count)}`;
    });
    readonly shadowEmpiricalProfitFactorProgress = computed(() => {
        const threshold = this.shadowEmpiricalProfitFactorThreshold();
        const value = this.shadowEmpiricalProfitFactor();
        if (threshold === null || value === null || threshold <= 0) {
            return null;
        }
        return Math.min(100, (value / threshold) * 100);
    });
    readonly shadowExpectedValue = computed<number | null>(() => this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.expected_value_usd));
    readonly shadowHoursProgress = computed(() => this.shadowStatus()?.hours_progress_percentage ?? 0);
    readonly shadowOutcomeProgress = computed(() => this.shadowStatus()?.outcome_progress_percentage ?? 0);

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

    readonly shadowRequiredCount = computed(() => this.shadowStatus()?.required_outcome_count ?? 0);

    readonly shadowRequiredHours = computed(() => this.shadowStatus()?.required_hours ?? 0);

    readonly shadowResolvedCount = computed(() => this.shadowStatus()?.resolved_outcome_count ?? 0);

    readonly shadowSparseExpectedValueGeometryLabel = computed(() => {
        const meta = this.shadowMeta();
        if (!meta) {
            return '—';
        }
        return `sparse ev ${this.formatShadowMetricLookbackDays(meta.sparse_expected_value_lookback_days)}d ${meta.sparse_expected_value_bucket_width_seconds}s p${meta.sparse_expected_value_moving_average_period}`;
    });

    readonly shadowSparseExpectedValueProgress = computed(() => {
        const ev = this.shadowSparseExpectedValueUsd();
        const threshold = this.shadowSparseExpectedValueUsdThreshold();
        if (ev === null || threshold === null) {
            return null;
        }
        if (threshold > 0) {
            return Math.min(100, (ev / threshold) * 100);
        }
        return ev >= threshold ? 100 : 0;
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

    readonly shadowWinRate = computed<number | null>(() => this.mapNullable(this.shadowMeta(), (shadowMeta) => shadowMeta.win_rate_percentage));

    readonly shouldShowReserveModeCard = computed(() => this.liquidityMode() === 'PAPER');

    readonly shouldShowLiquiditySyncCard = computed(() => !this.hasLiveBalances() && !this.shouldShowReserveModeCard());

    readonly unrealized = computed<number | null>(() => this.mapNullable(this.portfolio(), (portfolio) => portfolio.unrealized_profit_and_loss));

    formatMultiplier(value: number | null | undefined): string {
        if (value === null || value === undefined || !Number.isFinite(value)) {
            return '—';
        }
        if (value >= 900) {
            return '999+';
        }
        return value.toFixed(2);
    }

    /** Compact day display for shadow geometry captions (avoids "7.0" when unnecessary). */
    formatShadowMetricLookbackDays(days: number): string {
        if (Number.isInteger(days)) {
            return String(days);
        }
        const rounded = Math.round(days * 10) / 10;
        return rounded % 1 === 0 ? String(Math.round(rounded)) : rounded.toFixed(1);
    }

    formatShadowVerdictWindowToken(verdictCount: number): string {
        if (!Number.isFinite(verdictCount) || verdictCount <= 0) {
            return '—';
        }
        if (verdictCount % 1000 === 0 && verdictCount >= 1000) {
            const thousands = verdictCount / 1000;
            return `${thousands % 1 === 0 ? thousands : thousands.toFixed(1)}k verdicts`;
        }
        if (verdictCount >= 1000) {
            return `${(verdictCount / 1000).toFixed(1)}k verdicts`;
        }
        return `${verdictCount} verdicts`;
    }

    isNonNegative(value: number | null): boolean {
        if (value === null) {
            return false;
        }
        return value >= 0;
    }

    rangeArray(length: number): number[] {
        return Array.from({ length }, (_, index) => index);
    }

    private firstNonNull(...values: Array<number | null>): number | null {
        for (const value of values) {
            if (value !== null) {
                return value;
            }
        }
        return null;
    }

    private mapNullable<TSource, TProjected>(value: TSource | null, mapper: (value: TSource) => TProjected): TProjected | null {
        if (value === null) {
            return null;
        }
        return mapper(value);
    }
}
