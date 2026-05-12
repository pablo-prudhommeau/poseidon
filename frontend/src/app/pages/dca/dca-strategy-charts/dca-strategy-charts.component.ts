import { Component, computed, input } from '@angular/core';
import { ApexChart, ApexDataLabels, ApexFill, ApexGrid, ApexPlotOptions, ApexStroke, ApexTheme, ApexXAxis, ApexYAxis, NgApexchartsModule } from 'ng-apexcharts';
import { CardModule } from 'primeng/card';
import { DcaBacktestSeriesPointPayload, DcaOrderPayload, DcaStrategyPayload } from '../../../core/models';

@Component({
    standalone: true,
    selector: 'app-dca-strategy-charts',
    imports: [CardModule, NgApexchartsModule],
    templateUrl: './dca-strategy-charts.component.html'
})
export class DcaStrategyChartsComponent {
    public readonly drawdownConfig = {
        chart: {
            type: 'area',
            height: 250,
            toolbar: { show: false },
            background: 'transparent',
            sparkline: { enabled: false },
            animations: { enabled: false },
            zoom: { enabled: false }
        } as ApexChart,
        colors: [(options: { value: number }) => (options.value < 0 ? '#ef4444' : '#10b981')],
        stroke: { width: 2, curve: 'smooth' } as ApexStroke,
        fill: { type: 'gradient', gradient: { opacityFrom: 0.5, opacityTo: 0.1 } } as ApexFill,
        dataLabels: { enabled: false } as ApexDataLabels,
        xaxis: { type: 'datetime', labels: { show: false }, axisBorder: { show: false } } as ApexXAxis,
        yaxis: {
            labels: { style: { colors: '#94a3b8' }, formatter: (value: number) => `$${value.toFixed(0)}` }
        } as ApexYAxis,
        grid: { show: false } as ApexGrid,
        theme: { mode: 'dark' } as ApexTheme
    };

    public strategy = input.required<DcaStrategyPayload>();

    private readonly mappedMarketAndSmartData = computed(() => {
        const strat = this.strategy();
        if (!strat.historical_backtest_payload?.smart_dca_series || !strat.historical_backtest_payload?.dumb_dca_series) {
            return null;
        }

        const smartSeries: DcaBacktestSeriesPointPayload[] = strat.historical_backtest_payload.smart_dca_series;
        const baselineSeries: DcaBacktestSeriesPointPayload[] = strat.historical_backtest_payload.dumb_dca_series;

        const historicalStartTimestamp = new Date(baselineSeries[0].timestamp_iso).getTime();
        const historicalEndTimestamp = new Date(baselineSeries[baselineSeries.length - 1].timestamp_iso).getTime();
        const liveStartTimestamp = new Date(strat.strategy_start_date).getTime();
        const liveEndTimestamp = new Date(strat.strategy_end_date).getTime();

        const historicalStartPrice = baselineSeries[0].execution_price;
        const livePrice = this.calculateCurrentLivePrice(strat);
        const priceMultiplier = livePrice > 0 && historicalStartPrice > 0 ? livePrice / historicalStartPrice : 1;

        const mapTimeToLiveWindow = (historicalTimestamp: number) => {
            const timePercentage = (historicalTimestamp - historicalStartTimestamp) / (historicalEndTimestamp - historicalStartTimestamp);
            return liveStartTimestamp + timePercentage * (liveEndTimestamp - liveStartTimestamp);
        };

        const mappedSmartData = smartSeries.map((point) => [
            mapTimeToLiveWindow(new Date(point.timestamp_iso).getTime()),
            point.average_purchase_price * priceMultiplier
        ]);

        const mappedMarketPriceData = smartSeries.map((point) => [
            mapTimeToLiveWindow(new Date(point.timestamp_iso).getTime()),
            point.execution_price * priceMultiplier
        ]);

        return { mappedMarketPriceData, mappedSmartData };
    });

    public readonly drawdownSeries = computed(() => {
        const data = this.mappedMarketAndSmartData();
        if (!data) {
            return [];
        }
        const drawdownData = data.mappedMarketPriceData.map((point: number[], index: number) => [point[0], point[1] - data.mappedSmartData[index][1]]);
        return [{ name: 'PRU vs Price', data: drawdownData }];
    });

    public readonly dryPowderConfig = {
        chart: {
            type: 'radialBar',
            height: 280,
            background: 'transparent',
            animations: { enabled: false },
            zoom: { enabled: false }
        } as ApexChart,
        plotOptions: {
            radialBar: {
                hollow: { size: '40%' },
                track: { background: '#1e293b' },
                dataLabels: {
                    name: { show: true, color: '#94a3b8', fontSize: '12px' },
                    value: { color: '#fff', fontSize: '18px', formatter: (value: number) => value.toFixed(1) + '%' }
                }
            }
        } as ApexPlotOptions,
        labels: ['Time Elapsed', 'Budget Deployed'],
        colors: ['#38bdf8', '#10b981'],
        stroke: { lineCap: 'round' } as ApexStroke,
        theme: { mode: 'dark' } as ApexTheme
    };

    public readonly dryPowderSeries = computed<number[]>(() => {
        const strat = this.strategy();
        const startTimeTimestamp = new Date(strat.strategy_start_date).getTime();
        const endTimeTimestamp = new Date(strat.strategy_end_date).getTime();
        const currentTimestamp = Date.now();

        let timeElapsedPercentage = 0;
        if (currentTimestamp > endTimeTimestamp) {
            timeElapsedPercentage = 100;
        } else if (currentTimestamp > startTimeTimestamp) {
            timeElapsedPercentage = ((currentTimestamp - startTimeTimestamp) / (endTimeTimestamp - startTimeTimestamp)) * 100;
        }

        const progressPercentage = strat.total_allocated_budget > 0 ? (strat.total_deployed_amount / strat.total_allocated_budget) * 100 : 0;

        return [timeElapsedPercentage, progressPercentage];
    });

    public readonly jitterConfig = {
        chart: {
            type: 'scatter',
            height: 250,
            toolbar: { show: false },
            background: 'transparent',
            animations: { enabled: false },
            zoom: { enabled: false }
        } as ApexChart,
        xaxis: {
            type: 'numeric',
            min: 0,
            max: 24,
            tickAmount: 6,
            labels: { style: { colors: '#94a3b8' }, formatter: (value: string) => `${Math.floor(Number(value))}h` },
            title: { text: 'Local Hour of Day', style: { color: '#64748b', fontSize: '10px' } }
        } as ApexXAxis,
        yaxis: {
            labels: { style: { colors: '#94a3b8' }, formatter: (value: number) => `$${value.toFixed(0)}` }
        } as ApexYAxis,
        colors: ['#a855f7'],
        grid: { borderColor: '#1e293b', strokeDashArray: 4 } as ApexGrid,
        theme: { mode: 'dark' } as ApexTheme
    };

    public readonly jitterSeries = computed(() => {
        const strat = this.strategy();
        if (!strat.execution_orders) {
            return [];
        }
        const scatterData = strat.execution_orders
            .filter((order: DcaOrderPayload) => order.order_status === 'EXECUTED' && order.actual_execution_price !== null)
            .map((order: DcaOrderPayload) => {
                const executionDate = new Date(order.executed_at as string);
                const hourOfDay = executionDate.getHours() + executionDate.getMinutes() / 60;
                return [hourOfDay, order.actual_execution_price as number];
            });
        return [{ name: 'Snipes', data: scatterData }];
    });

    private calculateCurrentLivePrice(strategy: DcaStrategyPayload): number {
        if (!strategy.execution_orders) {
            return 0;
        }
        const executedOrders = strategy.execution_orders.filter((o: DcaOrderPayload) => o.order_status === 'EXECUTED' && o.actual_execution_price !== null);
        if (executedOrders.length === 0) {
            return 0;
        }
        executedOrders.sort((a, b) => new Date(b.executed_at as string).getTime() - new Date(a.executed_at as string).getTime());
        return executedOrders[0].actual_execution_price ?? 0;
    }
}
