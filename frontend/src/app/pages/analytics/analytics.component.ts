import {Component, inject, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {TabsModule} from 'primeng/tabs';
import {ApiService} from '../../api.service';
import {AnalyticsKpiBarComponent} from './analytics-kpi-bar/analytics-kpi-bar.component';
import {AnalyticsSynthesisComponent} from './analytics-synthesis/analytics-synthesis.component';
import {AnalyticsExplorationComponent} from './analytics-exploration/analytics-exploration.component';
import {AnalyticsResponse} from "../../core/models";

@Component({
    selector: 'app-analytics',
    standalone: true,
    imports: [
        CommonModule,
        TabsModule,
        AnalyticsKpiBarComponent,
        AnalyticsSynthesisComponent,
        AnalyticsExplorationComponent,
    ],
    templateUrl: './analytics.component.html',
    styleUrl: './analytics.component.css'
})
export class AnalyticsComponent implements OnInit {
    private readonly apiService = inject(ApiService);

    readonly analyticsData = signal<AnalyticsResponse | null>(null);
    readonly isLoading = signal<boolean>(true);
    readonly loadingError = signal<string | null>(null);

    readonly activeTabValue = signal<string>('0');

    ngOnInit(): void {
        this.loadAnalyticsData();
    }

    onTabChange(tabValue: string | number | undefined): void {
        this.activeTabValue.set(String(tabValue ?? '0'));
    }

    private loadAnalyticsData(): void {
        this.isLoading.set(true);
        this.loadingError.set(null);

        this.apiService.getAnalytics().subscribe({
            next: (response: AnalyticsResponse) => {
                this.analyticsData.set(response);
                this.isLoading.set(false);
                console.info('[ANALYTICS][HTTP][LOAD] Analytics data loaded', {
                    evaluations: response.kpis.total_evaluations,
                    outcomes: response.kpis.total_outcomes,
                    driversSeries: response.pnl_drivers_series.length,
                    timelinePoints: response.timeline.length,
                });
            },
            error: (error: unknown) => {
                this.isLoading.set(false);
                this.loadingError.set('Failed to load analytics data');
                console.error('[ANALYTICS][HTTP][LOAD][ERROR] Failed to load analytics data', error);
            },
        });
    }
}