import {Component, computed, inject} from '@angular/core';
import {CommonModule} from '@angular/common';
import {WebSocketService} from '../../../core/websocket.service';
import {TradingEquityCurvePointPayload, TradingPositionPayload} from '../../../core/models';
import {PositionsTableComponent} from '../../../features/positions/positions-table.component';
import {TradesTableComponent} from '../../../features/trades/trades-table.component';
import {PnlBadgeComponent} from '../../../widgets/pnl-badge/pnl-badge.component';
import {SparklineComponent} from '../../../widgets/sparkline/sparkline.component';

@Component({
    standalone: true,
    selector: 'app-trading-overview',
    imports: [CommonModule, PositionsTableComponent, TradesTableComponent, PnlBadgeComponent, SparklineComponent],
    templateUrl: './trading-overview.component.html'
})
export class TradingOverviewComponent {
    private readonly webSocketService = inject(WebSocketService);

    readonly equity = computed(() => this.webSocketService.portfolio()?.total_equity_value ?? 0);
    readonly cash = computed(() => this.webSocketService.portfolio()?.available_cash_balance ?? 0);
    readonly holdings = computed(() => this.webSocketService.portfolio()?.active_holdings_value ?? 0);
    readonly unrealized = computed(() => this.webSocketService.portfolio()?.unrealized_profit_and_loss ?? 0);
    readonly realizedTotal = computed(() => this.webSocketService.portfolio()?.realized_profit_and_loss_total ?? 0);
    readonly realized24h = computed(() => this.webSocketService.portfolio()?.realized_profit_and_loss_24h ?? 0);
    readonly equitySpark = computed<TradingEquityCurvePointPayload[]>(() => this.webSocketService.portfolio()?.equity_curve ?? []);

    readonly shadowStatus = computed(() => this.webSocketService.portfolio()?.shadow_intelligence_status);
    readonly shadowPhase = computed(() => this.shadowStatus()?.phase ?? 'DISABLED');
    readonly shadowOutcomeProgress = computed(() => this.shadowStatus()?.outcome_progress_percentage ?? 0);
    readonly shadowHoursProgress = computed(() => this.shadowStatus()?.hours_progress_percentage ?? 0);
    readonly shadowResolvedCount = computed(() => this.shadowStatus()?.resolved_outcome_count ?? 0);
    readonly shadowRequiredCount = computed(() => this.shadowStatus()?.required_outcome_count ?? 0);
    readonly shadowElapsedHours = computed(() => this.shadowStatus()?.elapsed_hours ?? 0);
    readonly shadowRequiredHours = computed(() => this.shadowStatus()?.required_hours ?? 0);

    readonly positions = computed<TradingPositionPayload[]>(() => this.webSocketService.positions());
    readonly openPositionCount = computed(() => this.positions().filter(position => position.position_phase === 'OPEN' || position.position_phase === 'PARTIAL').length);

    readonly deployedPercentage = computed(() => {
        const totalEquity = this.equity();
        if (totalEquity <= 0) {
            return 0;
        }
        return Math.min(100, (this.holdings() / totalEquity) * 100);
    });

    readonly bestPositionPnlPercentage = computed(() => {
        const openPositions = this.positions().filter(position => position.position_phase === 'OPEN' || position.position_phase === 'PARTIAL');
        if (openPositions.length === 0) {
            return 0;
        }
        return Math.max(...openPositions.map(position => {
            if (position.entry_price <= 0 || !position.last_price) {
                return 0;
            }
            return ((position.last_price - position.entry_price) / position.entry_price) * 100;
        }));
    });

    readonly worstPositionPnlPercentage = computed(() => {
        const openPositions = this.positions().filter(position => position.position_phase === 'OPEN' || position.position_phase === 'PARTIAL');
        if (openPositions.length === 0) {
            return 0;
        }
        return Math.min(...openPositions.map(position => {
            if (position.entry_price <= 0 || !position.last_price) {
                return 0;
            }
            return ((position.last_price - position.entry_price) / position.entry_price) * 100;
        }));
    });

    formatPnlSign(value: number): string {
        if (value > 0) {
            return '+';
        }
        return '';
    }
}
