import {NgClass} from '@angular/common';
import {Component, computed, input} from '@angular/core';
import {ApexChart, ApexDataLabels, ApexFill, ApexGrid, ApexLegend, ApexStroke, ApexTheme, ApexXAxis, ApexYAxis, NgApexchartsModule} from 'ng-apexcharts';
import {CardModule} from 'primeng/card';
import {DcaBacktestSeriesPointPayload, DcaOrderPayload, DcaStrategyPayload} from '../../../core/models';

@Component({
    standalone: true,
    selector: 'app-dca-strategy-path-projection',
    host: { class: 'block w-full' },
    imports: [NgClass, CardModule, NgApexchartsModule],
    templateUrl: './dca-strategy-path-projection.component.html'
})
export class DcaStrategyPathProjectionComponent {
    public strategy = input.required<DcaStrategyPayload>();

    public readonly engineStatus = computed<string>(() => this.strategy().strategy_status);

    public readonly mainChartConfig = {
        chart: {
            id: 'main-projection-chart',
            type: 'line',
            height: 400,
            toolbar: { show: false },
            background: 'transparent',
            animations: { enabled: false },
            zoom: { enabled: false }
        } as ApexChart,
        colors: ['#334155', '#ef4444', '#10b981'],
        stroke: { width: [1, 2, 3], curve: 'smooth', dashArray: [0, 4, 0] } as ApexStroke,
        fill: { type: ['gradient', 'solid', 'solid'], gradient: { opacityFrom: 0.2, opacityTo: 0.0 } } as ApexFill,
        dataLabels: { enabled: false } as ApexDataLabels,
        xaxis: {
            type: 'datetime',
            labels: {
                style: { colors: '#94a3b8' },
                datetimeUTC: false
            },
            axisBorder: { show: false }
        } as ApexXAxis,
        yaxis: {
            tickAmount: 8,
            labels: {
                style: { colors: '#94a3b8' },
                formatter: (value: number) => `$${value.toFixed(0)}`
            }
        } as ApexYAxis,
        grid: {
            show: true,
            borderColor: '#1e293b',
            strokeDashArray: 4,
            xaxis: { lines: { show: true } },
            yaxis: { lines: { show: true } }
        } as ApexGrid,
        theme: { mode: 'dark' } as ApexTheme,
        legend: { position: 'top', horizontalAlign: 'right', labels: { colors: '#f8fafc' } } as ApexLegend
    };

    private readonly mappedBacktestSeries = computed(() => {
        const strat = this.strategy();
        if (!strat.historical_backtest_payload) {
            return null;
        }

        const baselineSeries: DcaBacktestSeriesPointPayload[] = strat.historical_backtest_payload.dumb_dca_series;
        const smartSeries: DcaBacktestSeriesPointPayload[] = strat.historical_backtest_payload.smart_dca_series;

        if (!baselineSeries || baselineSeries.length === 0) {
            return null;
        }

        const historicalStartTimestamp = new Date(baselineSeries[0].timestamp_iso).getTime();
        const historicalEndTimestamp = new Date(baselineSeries[baselineSeries.length - 1].timestamp_iso).getTime();
        const historicalStartPrice = baselineSeries[0].execution_price;

        const liveStartTimestamp = new Date(strat.strategy_start_date).getTime();
        const liveEndTimestamp = new Date(strat.strategy_end_date).getTime();

        const livePrice = this.calculateCurrentLivePrice(strat);
        const priceMultiplier = livePrice > 0 && historicalStartPrice > 0 ? livePrice / historicalStartPrice : 1;

        const mapTimeToLiveWindow = (historicalTimestamp: number): number => {
            const timePercentage = (historicalTimestamp - historicalStartTimestamp) / (historicalEndTimestamp - historicalStartTimestamp);
            return liveStartTimestamp + timePercentage * (liveEndTimestamp - liveStartTimestamp);
        };

        const mappedBaselineData = baselineSeries.map((point) => [
            mapTimeToLiveWindow(new Date(point.timestamp_iso).getTime()),
            point.average_purchase_price * priceMultiplier
        ]);

        const mappedSmartData = smartSeries.map((point) => [
            mapTimeToLiveWindow(new Date(point.timestamp_iso).getTime()),
            point.average_purchase_price * priceMultiplier
        ]);

        const mappedMarketPriceData = smartSeries.map((point) => [
            mapTimeToLiveWindow(new Date(point.timestamp_iso).getTime()),
            point.execution_price * priceMultiplier
        ]);

        return { mappedMarketPriceData, mappedBaselineData, mappedSmartData };
    });

    public readonly mainSeries = computed(() => {
        const data = this.mappedBacktestSeries();
        if (!data) {
            return [];
        }
        return [
            { name: 'Projected Market Price', data: data.mappedMarketPriceData, type: 'area' },
            { name: 'Projected Baseline PRU', data: data.mappedBaselineData, type: 'line' },
            { name: 'Projected Smart PRU', data: data.mappedSmartData, type: 'line' }
        ];
    });

    private calculateCurrentLivePrice(strategy: DcaStrategyPayload): number {
        if (!strategy.execution_orders) {
            return 0;
        }
        const executedOrders = strategy.execution_orders.filter(
            (order: DcaOrderPayload) => order.order_status === 'EXECUTED' && order.actual_execution_price !== null
        );
        if (executedOrders.length === 0) {
            return 0;
        }
        executedOrders.sort((orderA, orderB) => new Date(orderB.executed_at as string).getTime() - new Date(orderA.executed_at as string).getTime());
        return executedOrders[0].actual_execution_price ?? 0;
    }
}
