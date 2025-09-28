import {DecimalPipe, NgIf} from '@angular/common';
import {Component, computed, OnInit} from '@angular/core';
import {ApiService} from '../api.service';
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
    constructor(public ws: WebSocketService, private api: ApiService) {}

    ngOnInit(): void {
        this.ws.connect();
    }

    // Metrics calculés (robustes aux null)
    equity = computed(() => this.ws.portfolio()?.equity ?? 0);
    cash = computed(() => this.ws.portfolio()?.cash ?? 0);
    holdings = computed(() => this.ws.portfolio()?.holdings ?? 0);
    unrealized = computed(() => this.ws.portfolio()?.unrealized_pnl ?? 0);
    realizedTotal = computed(() => this.ws.portfolio()?.realized_pnl_total ?? 0);
    realized24h = computed(() => this.ws.portfolio()?.realized_pnl_24h ?? 0);

    spark = computed<number[]>(() => this.ws.portfolio()?.equity_curve ?? []);

    resetPaper() {
        this.api.resetPaper().subscribe(() => {
            try { (this.ws as any)['socket']?.send(JSON.stringify({ type: 'refresh' })); } catch {}
        });
    }
}
