import {Component, inject, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {TabsModule} from 'primeng/tabs';
import {ButtonModule} from 'primeng/button';
import {ApiService} from '../../api.service';
import {AnalyticsResponse} from '../../core/models';
import {TradingOverviewComponent} from './trading-overview/trading-overview.component';
import {AnalyticsKpiBarComponent} from '../analytics/analytics-kpi-bar/analytics-kpi-bar.component';
import {AnalyticsSynthesisComponent} from '../analytics/analytics-synthesis/analytics-synthesis.component';
import {AnalyticsExplorationComponent} from '../analytics/analytics-exploration/analytics-exploration.component';
import {ShadowVerdictChronicleComponent} from './shadow-verdict-chronicle/components/shadow-verdict-chronicle.component';

@Component({
    standalone: true,
    selector: 'app-trading-dashboard',
    imports: [
        CommonModule,
        TabsModule,
        ButtonModule,
        TradingOverviewComponent,
        AnalyticsKpiBarComponent,
        AnalyticsSynthesisComponent,
        AnalyticsExplorationComponent,
        ShadowVerdictChronicleComponent,
    ],
    templateUrl: './trading-dashboard.component.html',
    styleUrl: './trading-dashboard.component.css'
})
export class TradingDashboardComponent implements OnInit {
    private readonly apiService = inject(ApiService);

    readonly activeTabValue = signal<string>('overview');

    readonly qualifiedAnalytics = signal<AnalyticsResponse | null>(null);
    readonly qualifiedLoading = signal<boolean>(false);
    readonly qualifiedError = signal<string | null>(null);

    readonly shadowAnalytics = signal<AnalyticsResponse | null>(null);
    readonly shadowLoading = signal<boolean>(false);
    readonly shadowError = signal<string | null>(null);

    readonly qualifiedAnalyticsSubTab = signal<string>('synthesis');
    readonly shadowAnalyticsSubTab = signal<string>('synthesis');

    ngOnInit(): void {
    }

    onTabChange(tabValue: string | number | undefined): void {
        const newTab = String(tabValue ?? 'overview');
        this.activeTabValue.set(newTab);

        if (newTab === 'analytics-qualified' && !this.qualifiedLoading()) {
            this.refreshQualifiedAnalytics();
        }

        if (newTab === 'analytics-shadow' && !this.shadowLoading()) {
            this.refreshShadowAnalytics();
        }
    }

    onQualifiedSubTabChange(tabValue: string | number | undefined): void {
        this.qualifiedAnalyticsSubTab.set(String(tabValue ?? 'synthesis'));
    }

    onShadowSubTabChange(tabValue: string | number | undefined): void {
        this.shadowAnalyticsSubTab.set(String(tabValue ?? 'synthesis'));
    }

    public refreshQualifiedAnalytics(): void {
        this.qualifiedLoading.set(true);
        this.qualifiedError.set(null);

        this.apiService.getAnalytics('qualified').subscribe({
            next: (response: AnalyticsResponse) => {
                this.qualifiedAnalytics.set(response);
                this.qualifiedLoading.set(false);
            },
            error: (error: unknown) => {
                this.qualifiedLoading.set(false);
                this.qualifiedError.set('Failed to load qualified analytics');
                console.error('[TRADING][ANALYTICS][QUALIFIED] Load error', error);
            },
        });
    }

    public refreshShadowAnalytics(): void {
        this.shadowLoading.set(true);
        this.shadowError.set(null);

        this.apiService.getAnalytics('shadow').subscribe({
            next: (response: AnalyticsResponse) => {
                this.shadowAnalytics.set(response);
                this.shadowLoading.set(false);
            },
            error: (error: unknown) => {
                this.shadowLoading.set(false);
                this.shadowError.set('Failed to load shadow analytics');
                console.error('[TRADING][ANALYTICS][SHADOW] Load error', error);
            },
        });
    }
}
