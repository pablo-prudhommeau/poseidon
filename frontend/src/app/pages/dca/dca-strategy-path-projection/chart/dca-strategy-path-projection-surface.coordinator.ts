import { DcaStrategyPayload } from '../../../../core/models';
import { DcaStrategyPathChartModel, DcaStrategyPathChartSeriesBundle } from '../data/dca-strategy-path-projection.models';
import { buildStrategyPathChartSeriesBundle } from '../data/dca-strategy-path-projection-series-data.utils';
import type { DcaStrategyPathLegendSeriesItem } from './dca-strategy-path-projection-legend.adapter';
import { listDcaStrategyPathLegendSeries, setDcaStrategyPathSeriesVisibility } from './dca-strategy-path-projection-legend.adapter';
import { DcaStrategyPathProjectionSurfaceBuilder } from './dca-strategy-path-projection-surface.builder';
import { DcaStrategyPathProjectionSciChartLoaderService } from '../services/dca-strategy-path-projection-scichart-loader.service';

export class DcaStrategyPathProjectionSurfaceCoordinator {
    private buildGeneration: number = 0;
    private buildPromise: Promise<void> | undefined;
    private chartModel: DcaStrategyPathChartModel | undefined;
    private readonly surfaceBuilder: DcaStrategyPathProjectionSurfaceBuilder = new DcaStrategyPathProjectionSurfaceBuilder();

    constructor(private readonly sciChartLoader: DcaStrategyPathProjectionSciChartLoaderService) {}

    hasChartModel(): boolean {
        return this.chartModel !== undefined;
    }

    listLegendSeries(): DcaStrategyPathLegendSeriesItem[] {
        const model = this.chartModel;
        if (!model) {
            return [];
        }
        return listDcaStrategyPathLegendSeries(model);
    }

    setSeriesVisibility(seriesName: string, isVisible: boolean): void {
        const model = this.chartModel;
        if (!model) {
            return;
        }
        setDcaStrategyPathSeriesVisibility(model, seriesName, isVisible);
        model.sciChartSurface.invalidateElement();
    }

    async synchronizeChartSurface(host: HTMLDivElement, strategy: DcaStrategyPayload): Promise<void> {
        const buildGeneration: number = this.buildGeneration;
        const seriesBundle: DcaStrategyPathChartSeriesBundle | null = buildStrategyPathChartSeriesBundle(strategy);
        if (!seriesBundle) {
            this.teardownChartSurface();
            return;
        }

        if (!host.isConnected || host.clientWidth <= 0 || host.clientHeight <= 0) {
            return;
        }

        if (this.chartModel) {
            await this.surfaceBuilder.synchronizeChartData(this.chartModel, seriesBundle, this.sciChartLoader);
            return;
        }

        if (this.buildPromise) {
            await this.buildPromise;
            if (buildGeneration !== this.buildGeneration) {
                return;
            }
            if (this.chartModel) {
                await this.surfaceBuilder.synchronizeChartData(this.chartModel, seriesBundle, this.sciChartLoader);
                return;
            }
        }

        this.buildPromise = (async (): Promise<void> => {
            if (buildGeneration !== this.buildGeneration || !host.isConnected || host.clientWidth <= 0 || host.clientHeight <= 0) {
                return;
            }
            this.chartModel = await this.surfaceBuilder.buildChartSurface(host, strategy, seriesBundle, this.sciChartLoader);
        })();

        try {
            await this.buildPromise;
        } catch {
            this.teardownChartSurface(host);
        } finally {
            this.buildPromise = undefined;
        }
    }

    teardownChartSurface(host?: HTMLDivElement): void {
        this.buildGeneration += 1;
        this.buildPromise = undefined;

        if (this.chartModel) {
            try {
                this.chartModel.sciChartSurface.delete();
            } catch {
                void 0;
            }
            this.chartModel = undefined;
        }

        if (host) {
            host.replaceChildren();
        }
    }
}
