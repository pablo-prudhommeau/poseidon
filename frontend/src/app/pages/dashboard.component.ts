import {DecimalPipe, NgIf} from '@angular/common';
import {Component, computed, OnInit} from '@angular/core';
import {ApiService} from '../api.service';
import {EquityCurvePoint} from '../core/models';
import {WebSocketService} from '../core/websocket.service';
import {PositionsTableComponent} from '../features/positions/positions-table.component';
import {TradesTableComponent} from '../features/trades/trades-table.component';
import {PnlBadgeComponent} from '../widgets/pnl-badge.component';
import {SparklineComponent} from '../widgets/sparkline.component';

@Component({
    standalone: true,
    selector: 'app-dashboard',
    imports: [DecimalPipe, PositionsTableComponent, TradesTableComponent, PnlBadgeComponent, SparklineComponent, NgIf],
    templateUrl: './dashboard.component.html'
})
export class DashboardComponent implements OnInit {
    constructor(public webSocketService: WebSocketService, private api: ApiService) {}

    ngOnInit(): void {
        this.webSocketService.connect();
    }

    equity = computed(() => this.webSocketService.portfolio()?.equity ?? 0);
    cash = computed(() => this.webSocketService.portfolio()?.cash ?? 0);
    holdings = computed(() => this.webSocketService.portfolio()?.holdings ?? 0);
    unrealized = computed(() => this.webSocketService.portfolio()?.unrealized_pnl ?? 0);
    realizedTotal = computed(() => this.webSocketService.portfolio()?.realized_pnl_total ?? 0);
    realized24h = computed(() => this.webSocketService.portfolio()?.realized_pnl_24h ?? 0);
    spark = computed<EquityCurvePoint[]>(() => this.webSocketService.portfolio()?.equity_curve ?? []);

    resetPaper() {
        this.api.resetPaper().subscribe(() => {
            try { (this.webSocketService as any)['socket']?.send(JSON.stringify({ type: 'refresh' })); } catch {}
        });
    }
}
