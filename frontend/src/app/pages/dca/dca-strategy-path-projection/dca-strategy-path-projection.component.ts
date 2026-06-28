import { Component, computed, effect, ElementRef, inject, input, OnDestroy, signal, untracked, viewChild } from '@angular/core';
import { CardModule } from 'primeng/card';
import { DcaStrategyPayload } from '../../../core/models';
import { hasExecutedDcaOrders } from '../dca-execution.utils';
import type { DcaStrategyPathLegendSeriesItem } from './chart/dca-strategy-path-projection-legend.adapter';
import { DcaStrategyPathProjectionSurfaceCoordinator } from './chart/dca-strategy-path-projection-surface.coordinator';
import { dcaStrategyPathSeriesDisplayLabel } from './data/dca-strategy-path-projection-legend.utils';
import {
    DCA_STRATEGY_PATH_BACKTESTING_METRIC_SERIES_NAMES,
    DCA_STRATEGY_PATH_BAND_METRIC_SERIES_NAMES,
    DCA_STRATEGY_PATH_EFFECTIVE_METRIC_SERIES_NAMES,
    DCA_STRATEGY_PATH_PROJECTED_METRIC_SERIES_NAMES
} from './data/dca-strategy-path-projection-metric-groups';
import { resolveDcaStrategyPathMetricGroupToggleState } from './data/dca-strategy-path-projection-metric-group-state.utils';
import { DcaStrategyPathProjectionSciChartLoaderService } from './services/dca-strategy-path-projection-scichart-loader.service';

@Component({
    standalone: true,
    selector: 'app-dca-strategy-path-projection',
    host: { class: 'block w-full' },
    imports: [CardModule],
    templateUrl: './dca-strategy-path-projection.component.html',
    styleUrl: './dca-strategy-path-projection.component.css'
})
export class DcaStrategyPathProjectionComponent implements OnDestroy {
    public readonly legendItems = signal<DcaStrategyPathLegendSeriesItem[]>([]);

    public readonly allMetricsAvailable = computed<boolean>(() => this.legendItems().length > 0);

    public readonly allMetricsChecked = computed<boolean>(() => {
        const legendItems: DcaStrategyPathLegendSeriesItem[] = this.legendItems();
        return legendItems.length > 0 && legendItems.every((legendItem: DcaStrategyPathLegendSeriesItem) => legendItem.visible);
    });
    public readonly allMetricsMixed = computed<boolean>(() => {
        const legendItems: DcaStrategyPathLegendSeriesItem[] = this.legendItems();
        return legendItems.some((legendItem: DcaStrategyPathLegendSeriesItem) => legendItem.visible) && !this.allMetricsChecked();
    });

    public readonly backtestingMetricsToggleState = computed(() =>
        resolveDcaStrategyPathMetricGroupToggleState(this.legendItems(), DCA_STRATEGY_PATH_BACKTESTING_METRIC_SERIES_NAMES)
    );

    public readonly bandsMetricsToggleState = computed(() =>
        resolveDcaStrategyPathMetricGroupToggleState(this.legendItems(), DCA_STRATEGY_PATH_BAND_METRIC_SERIES_NAMES)
    );

    public readonly effectiveMetricsToggleState = computed(() =>
        resolveDcaStrategyPathMetricGroupToggleState(this.legendItems(), DCA_STRATEGY_PATH_EFFECTIVE_METRIC_SERIES_NAMES)
    );

    public strategy = input.required<DcaStrategyPayload>();

    public readonly hasExecutedOrders = computed<boolean>(() => hasExecutedDcaOrders(this.strategy()));

    public readonly projectedMetricsToggleState = computed(() =>
        resolveDcaStrategyPathMetricGroupToggleState(this.legendItems(), DCA_STRATEGY_PATH_PROJECTED_METRIC_SERIES_NAMES)
    );

    public readonly showLegendPanel = signal<boolean>(true);

    private readonly chartHost = viewChild<ElementRef<HTMLDivElement>>('chartHost');
    private readonly sciChartLoader: DcaStrategyPathProjectionSciChartLoaderService = inject(DcaStrategyPathProjectionSciChartLoaderService);
    private readonly surfaceCoordinator: DcaStrategyPathProjectionSurfaceCoordinator = new DcaStrategyPathProjectionSurfaceCoordinator(this.sciChartLoader);

    constructor() {
        effect((onCleanup) => {
            const strategy: DcaStrategyPayload = this.strategy();
            const hasExecutedOrders: boolean = this.hasExecutedOrders();

            if (!hasExecutedOrders) {
                untracked(() => {
                    const hostElement: HTMLDivElement | undefined = this.chartHost()?.nativeElement;
                    this.surfaceCoordinator.teardownChartSurface(hostElement);
                    this.legendItems.set([]);
                    this.showLegendPanel.set(true);
                });
                return;
            }

            let cancelled: boolean = false;
            onCleanup(() => {
                cancelled = true;
            });

            untracked(() => {
                void this.scheduleChartSynchronization(strategy, () => cancelled);
            });
        });
    }

    ngOnDestroy(): void {
        const hostElement: HTMLDivElement | undefined = this.chartHost()?.nativeElement;
        this.surfaceCoordinator.teardownChartSurface(hostElement);
    }

    legendSeriesLabel(seriesName: string): string {
        return dcaStrategyPathSeriesDisplayLabel(seriesName);
    }

    onAllMetricsToggle(nextVisible: boolean): void {
        for (const legendItem of this.legendItems()) {
            this.surfaceCoordinator.setSeriesVisibility(legendItem.name, nextVisible);
        }
        this.syncLegendFromChart();
    }

    onBacktestingMetricsToggle(nextVisible: boolean): void {
        this.setMetricGroupVisibility(DCA_STRATEGY_PATH_BACKTESTING_METRIC_SERIES_NAMES, nextVisible);
    }

    onBandsMetricsToggle(nextVisible: boolean): void {
        this.setMetricGroupVisibility(DCA_STRATEGY_PATH_BAND_METRIC_SERIES_NAMES, nextVisible);
    }

    onEffectiveMetricsToggle(nextVisible: boolean): void {
        this.setMetricGroupVisibility(DCA_STRATEGY_PATH_EFFECTIVE_METRIC_SERIES_NAMES, nextVisible);
    }

    onLegendItemToggle(seriesName: string, nextVisible: boolean): void {
        this.surfaceCoordinator.setSeriesVisibility(seriesName, nextVisible);
        this.syncLegendFromChart();
    }

    onProjectedMetricsToggle(nextVisible: boolean): void {
        this.setMetricGroupVisibility(DCA_STRATEGY_PATH_PROJECTED_METRIC_SERIES_NAMES, nextVisible);
    }

    toggleLegendPanel(): void {
        this.showLegendPanel.update((value) => !value);
    }

    private async scheduleChartSynchronization(strategy: DcaStrategyPayload, isCancelled: () => boolean): Promise<void> {
        for (let attempt = 0; attempt < 24; attempt++) {
            if (isCancelled()) {
                return;
            }

            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

            const hostElement: HTMLDivElement | undefined = this.chartHost()?.nativeElement;
            if (hostElement && hostElement.isConnected && hostElement.clientWidth > 0 && hostElement.clientHeight > 0) {
                if (isCancelled()) {
                    return;
                }
                await this.surfaceCoordinator.synchronizeChartSurface(hostElement, strategy);
                if (!isCancelled()) {
                    this.syncLegendFromChart();
                }
                return;
            }

            await new Promise<void>((resolve) => setTimeout(resolve, 20));
        }
    }

    private setMetricGroupVisibility(seriesNames: string[], nextVisible: boolean): void {
        for (const legendItem of this.legendItems()) {
            if (seriesNames.includes(legendItem.name)) {
                this.surfaceCoordinator.setSeriesVisibility(legendItem.name, nextVisible);
            }
        }
        this.syncLegendFromChart();
    }

    private syncLegendFromChart(): void {
        this.legendItems.set(this.surfaceCoordinator.listLegendSeries());
    }
}
