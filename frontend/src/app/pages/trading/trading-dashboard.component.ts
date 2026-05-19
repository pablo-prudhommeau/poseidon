import { CommonModule } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { ButtonModule } from 'primeng/button';
import { TabsModule } from 'primeng/tabs';
import { ApiService } from '../../api.service';
import { TradingAnalyticsResponse } from '../../core/models';
import { TradingAnalyticsExplorationComponent } from './trading-analytics-exploration/trading-analytics-exploration.component';
import { TradingAnalyticsKpiBarComponent } from './trading-analytics-kpi-bar/trading-analytics-kpi-bar.component';
import { TradingAnalyticsSynthesisComponent } from './trading-analytics-synthesis/trading-analytics-synthesis.component';
import { TradingShadowingVerdictChronicleComponent } from './trading-shadowing-verdict-chronicle/components/trading-shadowing-verdict-chronicle.component';
import { TradingOverviewComponent } from './trading-overview/trading-overview.component';

@Component({
    standalone: true,
    selector: 'app-trading-dashboard',
    imports: [
        CommonModule,
        TabsModule,
        ButtonModule,
        TradingOverviewComponent,
        TradingAnalyticsKpiBarComponent,
        TradingAnalyticsSynthesisComponent,
        TradingAnalyticsExplorationComponent,
        TradingShadowingVerdictChronicleComponent
    ],
    templateUrl: './trading-dashboard.component.html',
    styleUrl: './trading-dashboard.component.css'
})
export class TradingDashboardComponent implements OnInit {
    readonly activeTabValue = signal<string>('overview');
    readonly tradingAnalytics = signal<TradingAnalyticsResponse | null>(null);
    readonly tradingAnalyticsError = signal<string | null>(null);
    readonly tradingAnalyticsLoading = signal<boolean>(false);
    readonly tradingAnalyticsSubTab = signal<string>('synthesis');
    readonly tradingShadowingAnalytics = signal<TradingAnalyticsResponse | null>(null);
    readonly tradingShadowingAnalyticsError = signal<string | null>(null);
    readonly tradingShadowingAnalyticsLoading = signal<boolean>(false);
    readonly tradingShadowingAnalyticsSubTab = signal<string>('synthesis');

    private readonly apiService = inject(ApiService);

    ngOnInit(): void {}

    onTabChange(tabValue: string | number | undefined): void {
        const newTab = String(tabValue ?? 'overview');
        this.activeTabValue.set(newTab);

        if (newTab === 'trading-analytics' && !this.tradingAnalyticsLoading()) {
            this.refreshTradingAnalytics();
        }

        if (newTab === 'trading-shadowing-analytics' && !this.tradingShadowingAnalyticsLoading()) {
            this.refreshTradingShadowingAnalytics();
        }
    }

    onTradingAnalyticsSubTabChange(tabValue: string | number | undefined): void {
        this.tradingAnalyticsSubTab.set(String(tabValue ?? 'synthesis'));
    }

    onTradingShadowingAnalyticsSubTabChange(tabValue: string | number | undefined): void {
        this.tradingShadowingAnalyticsSubTab.set(String(tabValue ?? 'synthesis'));
    }

    public refreshTradingAnalytics(): void {
        this.tradingAnalyticsLoading.set(true);
        this.tradingAnalyticsError.set(null);

        this.apiService.getTradingAnalytics('qualified').subscribe({
            next: (response: TradingAnalyticsResponse) => {
                this.tradingAnalytics.set(response);
                this.tradingAnalyticsLoading.set(false);
            },
            error: (error: unknown) => {
                this.tradingAnalyticsLoading.set(false);
                this.tradingAnalyticsError.set('Failed to load trading analytics');
                console.error('[TRADING][ANALYTICS][QUALIFIED] Load error', error);
            }
        });
    }

    public refreshTradingShadowingAnalytics(): void {
        this.tradingShadowingAnalyticsLoading.set(true);
        this.tradingShadowingAnalyticsError.set(null);

        this.apiService.getTradingAnalytics('shadow').subscribe({
            next: (response: TradingAnalyticsResponse) => {
                this.tradingShadowingAnalytics.set(response);
                this.tradingShadowingAnalyticsLoading.set(false);
            },
            error: (error: unknown) => {
                this.tradingShadowingAnalyticsLoading.set(false);
                this.tradingShadowingAnalyticsError.set('Failed to load trading shadowing analytics');
                console.error('[TRADING][ANALYTICS][SHADOWING] Load error', error);
            }
        });
    }
}
