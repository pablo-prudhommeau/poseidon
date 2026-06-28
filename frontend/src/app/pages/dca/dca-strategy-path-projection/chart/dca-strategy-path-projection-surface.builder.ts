import { DcaStrategyPayload } from '../../../../core/models';
import { DcaStrategyPathChartModel, DcaStrategyPathChartSeriesBundle } from '../data/dca-strategy-path-projection.models';
import { DcaStrategyPathProjectionSciChartLoaderService } from '../services/dca-strategy-path-projection-scichart-loader.service';
import { DcaStrategyPathProjectionSeriesBuilder } from './dca-strategy-path-projection-series.builder';

export class DcaStrategyPathProjectionSurfaceBuilder {
    private readonly seriesBuilder: DcaStrategyPathProjectionSeriesBuilder = new DcaStrategyPathProjectionSeriesBuilder();

    async buildChartSurface(
        host: HTMLDivElement,
        strategy: DcaStrategyPayload,
        seriesBundle: DcaStrategyPathChartSeriesBundle,
        sciChartLoader: DcaStrategyPathProjectionSciChartLoaderService
    ): Promise<DcaStrategyPathChartModel> {
        return this.seriesBuilder.buildChartModel(host, strategy, seriesBundle, sciChartLoader);
    }

    async synchronizeChartData(
        chartModel: DcaStrategyPathChartModel,
        seriesBundle: DcaStrategyPathChartSeriesBundle,
        sciChartLoader: DcaStrategyPathProjectionSciChartLoaderService
    ): Promise<void> {
        const sciChartModule = await sciChartLoader.loadModule();
        this.seriesBuilder.synchronizeChartModel(chartModel, seriesBundle, sciChartModule);
    }
}
