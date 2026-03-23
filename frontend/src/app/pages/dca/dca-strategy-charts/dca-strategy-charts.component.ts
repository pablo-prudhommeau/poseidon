import {Component, computed, input} from '@angular/core';
import {CardModule} from 'primeng/card';
import {ApexChart, ApexDataLabels, ApexFill, ApexGrid, ApexPlotOptions, ApexStroke, ApexTheme, ApexXAxis, ApexYAxis, NgApexchartsModule} from 'ng-apexcharts';
import {DcaBacktestSeriesPoint, DcaOrder, DcaStrategy} from '../../../core/models';

@Component({
    standalone: true,
    selector: 'app-dca-strategy-charts',
    imports: [CardModule, NgApexchartsModule],
    templateUrl: './dca-strategy-charts.component.html'
})
export class DcaStrategyChartsComponent {
    public strategy = input.required<DcaStrategy>();

    private readonly mappedMarketAndSmartData = computed(() => {
        const strat = this.strategy();
        if (!strat.backtest_payload?.smart_dca_series || !strat.backtest_payload?.dumb_dca_series) {
            return null;
        }

        const smartSeries: DcaBacktestSeriesPoint[] = strat.backtest_payload.smart_dca_series;
        const baselineSeries: DcaBacktestSeriesPoint[] = strat.backtest_payload.dumb_dca_series;

        const historicalStartTimestamp = new Date(baselineSeries[0].timestamp_iso).getTime();
        const historicalEndTimestamp = new Date(baselineSeries[baselineSeries.length - 1].timestamp_iso).getTime();
        const liveStartTimestamp = new Date(strat.start_date).getTime();
        const liveEndTimestamp = new Date(strat.end_date).getTime();

        const historicalStartPrice = baselineSeries[0].execution_price;
        const livePrice = this.calculateCurrentLivePrice(strat);
        const priceMultiplier = (livePrice > 0 && historicalStartPrice > 0) ? (livePrice / historicalStartPrice) : 1;

        const mapTimeToLiveWindow = (historicalTimestamp: number) => {
            const timePercentage = (historicalTimestamp - historicalStartTimestamp) / (historicalEndTimestamp - historicalStartTimestamp);
            return liveStartTimestamp + timePercentage * (liveEndTimestamp - liveStartTimestamp);
        };

        const mappedSmartData = smartSeries.map(point => [
            mapTimeToLiveWindow(new Date(point.timestamp_iso).getTime()),
            point.average_purchase_price * priceMultiplier
        ]);

        const mappedMarketPriceData = smartSeries.map(point => [
            mapTimeToLiveWindow(new Date(point.timestamp_iso).getTime()),
            point.execution_price * priceMultiplier
        ]);

        return {mappedMarketPriceData, mappedSmartData};
    });

    public readonly drawdownSeries = computed(() => {
        const data = this.mappedMarketAndSmartData();
        if (!data) {
            return [];
        }
        const drawdownData = data.mappedMarketPriceData.map((point: number[], index: number) => [
            point[0],
            point[1] - data.mappedSmartData[index][1]
        ]);
        return [{name: "PRU vs Price", data: drawdownData}];
    });

    public readonly dryPowderSeries = computed<number[]>(() => {
        const strat = this.strategy();
        const startTimeTimestamp = new Date(strat.start_date).getTime();
        const endTimeTimestamp = new Date(strat.end_date).getTime();
        const currentTimestamp = Date.now();

        let timeElapsedPercentage = 0;
        if (currentTimestamp > endTimeTimestamp) {
            timeElapsedPercentage = 100;
        } else if (currentTimestamp > startTimeTimestamp) {
            timeElapsedPercentage = ((currentTimestamp - startTimeTimestamp) / (endTimeTimestamp - startTimeTimestamp)) * 100;
        }

        const progressPercentage = strat.total_budget > 0 ? (strat.deployed_amount / strat.total_budget) * 100 : 0;

        return [timeElapsedPercentage, progressPercentage];
    });

    public readonly jitterSeries = computed(() => {
        const strat = this.strategy();
        if (!strat.orders) {
            return [];
        }
        const scatterData = strat.orders
            .filter((order: DcaOrder) => order.status === 'EXECUTED' && order.execution_price !== null)
            .map((order: DcaOrder) => {
                const executionDate = new Date(order.executed_at as string);
                const hourOfDay = executionDate.getHours() + (executionDate.getMinutes() / 60);
                return [hourOfDay, order.execution_price as number];
            });
        return [{name: "Snipes", data: scatterData}];
    });

    public readonly drawdownConfig = {
        chart: {type: 'area', height: 250, toolbar: {show: false}, background: 'transparent', sparkline: {enabled: false}, animations: {enabled: false}, zoom: {enabled: false}} as ApexChart,
        colors: [(options: { value: number }) => options.value < 0 ? '#ef4444' : '#10b981'],
        stroke: {width: 2, curve: 'smooth'} as ApexStroke,
        fill: {type: 'gradient', gradient: {opacityFrom: 0.5, opacityTo: 0.1}} as ApexFill,
        dataLabels: {enabled: false} as ApexDataLabels,
        xaxis: {type: 'datetime', labels: {show: false}, axisBorder: {show: false}} as ApexXAxis,
        yaxis: {labels: {style: {colors: '#94a3b8'}, formatter: (value: number) => `$${value.toFixed(0)}`}} as ApexYAxis,
        grid: {show: false} as ApexGrid,
        theme: {mode: 'dark'} as ApexTheme
    };

    public readonly dryPowderConfig = {
        chart: {type: 'radialBar', height: 280, background: 'transparent', animations: {enabled: false}, zoom: {enabled: false}} as ApexChart,
        plotOptions: {
            radialBar: {
                hollow: {size: '40%'},
                track: {background: '#1e293b'},
                dataLabels: {
                    name: {show: true, color: '#94a3b8', fontSize: '12px'},
                    value: {color: '#fff', fontSize: '18px', formatter: (value: number) => value.toFixed(1) + '%'}
                }
            }
        } as ApexPlotOptions,
        labels: ['Time Elapsed', 'Budget Deployed'],
        colors: ['#38bdf8', '#10b981'],
        stroke: {lineCap: 'round'} as ApexStroke,
        theme: {mode: 'dark'} as ApexTheme
    };

    public readonly jitterConfig = {
        chart: {type: 'scatter', height: 250, toolbar: {show: false}, background: 'transparent', animations: {enabled: false}, zoom: {enabled: false}} as ApexChart,
        xaxis: {
            type: 'numeric', min: 0, max: 24, tickAmount: 6,
            labels: {style: {colors: '#94a3b8'}, formatter: (value: string) => `${Math.floor(Number(value))}h`},
            title: {text: 'Local Hour of Day', style: {color: '#64748b', fontSize: '10px'}}
        } as ApexXAxis,
        yaxis: {labels: {style: {colors: '#94a3b8'}, formatter: (value: number) => `$${value.toFixed(0)}`}} as ApexYAxis,
        colors: ['#a855f7'],
        grid: {borderColor: '#1e293b', strokeDashArray: 4} as ApexGrid,
        theme: {mode: 'dark'} as ApexTheme
    };

    private calculateCurrentLivePrice(strategy: DcaStrategy): number {
        if (!strategy.orders) {
            return 0;
        }
        const executedOrders = strategy.orders.filter((o: DcaOrder) => o.status === 'EXECUTED' && o.execution_price !== null);
        if (executedOrders.length === 0) {
            return 0;
        }
        executedOrders.sort((a, b) => new Date(b.executed_at as string).getTime() - new Date(a.executed_at as string).getTime());
        return executedOrders[0].execution_price ?? 0;
    }
}