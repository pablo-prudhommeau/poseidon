import {DecimalPipe} from '@angular/common';
import {Component, computed} from '@angular/core';
import {CardModule} from 'primeng/card';
import {TradingEquityCurvePointPayload} from '../../core/models';
import {WebSocketService} from '../../core/websocket.service';
import {PositionsTableComponent} from '../../features/positions/positions-table.component';
import {TradesTableComponent} from '../../features/trades/trades-table.component';
import {PnlBadgeComponent} from '../../widgets/pnl-badge/pnl-badge.component';
import {SparklineComponent} from '../../widgets/sparkline/sparkline.component';

@Component({
    standalone: true,
    selector: 'app-dashboard',
    imports: [DecimalPipe, CardModule, PositionsTableComponent, TradesTableComponent, PnlBadgeComponent, SparklineComponent],
    templateUrl: './dashboard.component.html'
})
export class DashboardComponent {
    constructor(public webSocketService: WebSocketService) {}

    equity = computed(() => this.webSocketService.portfolio()?.total_equity_value ?? 0);
    cash = computed(() => this.webSocketService.portfolio()?.available_cash_balance ?? 0);
    holdings = computed(() => this.webSocketService.portfolio()?.active_holdings_value ?? 0);
    unrealized = computed(() => this.webSocketService.portfolio()?.unrealized_profit_and_loss ?? 0);
    realizedTotal = computed(() => this.webSocketService.portfolio()?.realized_profit_and_loss_total ?? 0);
    realized24h = computed(() => this.webSocketService.portfolio()?.realized_profit_and_loss_24h ?? 0);
    spark = computed<TradingEquityCurvePointPayload[]>(() => this.webSocketService.portfolio()?.equity_curve ?? []);
}
