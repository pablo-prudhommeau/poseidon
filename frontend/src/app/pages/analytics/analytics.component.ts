import {Component, inject, OnInit, signal} from '@angular/core';
import {CommonModule} from '@angular/common';
import {TabsModule} from 'primeng/tabs';
import {ApiService} from '../../api.service';
import {AnalyticsKpiBarComponent} from './analytics-kpi-bar.component';
import {AnalyticsSynthesisComponent} from './analytics-synthesis.component';
import {AnalyticsExplorationComponent} from './analytics-exploration.component';
import {AnalyticsAggregatedResponse} from "../../core/models";

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
    styles: [`
        :host {
            display: block;
        }

        .analytics-loading {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 400px;
            color: #9ca3af;
            font-size: 1rem;
        }

        .analytics-loading-spinner {
            width: 32px;
            height: 32px;
            border: 3px solid rgba(124, 92, 255, 0.2);
            border-top-color: #7c5cff;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 12px;
        }

        @keyframes spin {
            to {
                transform: rotate(360deg);
            }
        }

        .analytics-error {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 200px;
            color: #ef4444;
            font-size: 0.9rem;
        }

        :host ::ng-deep .p-tabs-nav {
            border-bottom: 1px solid rgba(124, 92, 255, 0.2);
        }

        :host ::ng-deep .p-tab {
            font-size: 0.9rem;
            padding: 0.6rem 1.2rem;
        }
    `]
})
export class AnalyticsComponent implements OnInit {
    private readonly apiService = inject(ApiService);

    readonly aggregatedData = signal<AnalyticsAggregatedResponse | null>(null);
    readonly isLoading = signal<boolean>(true);
    readonly loadingError = signal<string | null>(null);

    readonly activeTabValue = signal<string>('0');

    ngOnInit(): void {
        this.loadAggregatedAnalytics();
    }

    onTabChange(tabValue: string | number | undefined): void {
        this.activeTabValue.set(String(tabValue ?? '0'));
    }

    private loadAggregatedAnalytics(): void {
        this.isLoading.set(true);
        this.loadingError.set(null);

        this.apiService.getAggregatedAnalytics().subscribe({
            next: (response: AnalyticsAggregatedResponse) => {
                this.aggregatedData.set(response);
                this.isLoading.set(false);
                console.info('[ANALYTICS][HTTP][LOAD] Aggregated analytics loaded', {
                    evaluations: response.kpis.total_evaluations,
                    outcomes: response.kpis.total_outcomes,
                    driversSeries: response.pnl_drivers_series.length,
                    timelinePoints: response.timeline.length,
                });
            },
            error: (error: unknown) => {
                this.isLoading.set(false);
                this.loadingError.set('Failed to load analytics data');
                console.error('[ANALYTICS][HTTP][LOAD][ERROR] Failed to load aggregated analytics', error);
            },
        });
    }
}