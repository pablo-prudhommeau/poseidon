import {Component, Input, OnChanges, SimpleChanges} from '@angular/core';
import {CommonModule} from '@angular/common';
import {ApexAxisChartSeries, ApexChart, ApexFill, ApexStroke, ApexTooltip, NgApexchartsModule} from 'ng-apexcharts';
import {POSEIDON_COLORS} from '../../apex.theme';
import {AnalyticsKpiPayload, AnalyticsTimelinePointPayload} from "../../core/models";

@Component({
    selector: 'app-analytics-kpi-bar',
    standalone: true,
    imports: [CommonModule, NgApexchartsModule],
    templateUrl: 'analytics-kpi-bar.component.html',
    styles: [`
        :host {
            display: block;
        }
    `]
})
export class AnalyticsKpiBarComponent implements OnChanges {
    @Input() kpis: AnalyticsKpiPayload | null = null;
    @Input() timeline: AnalyticsTimelinePointPayload[] = [];

    sparklineSeries: ApexAxisChartSeries = [];
    sparklineChart: ApexChart = {
        type: 'area',
        height: 80,
        sparkline: {enabled: true},
        animations: {enabled: false}
    };
    sparklineStroke: ApexStroke = {curve: 'smooth', width: 2, colors: [POSEIDON_COLORS.accent]};
    sparklineFill: ApexFill = {
        type: 'gradient',
        gradient: {
            shadeIntensity: 1,
            opacityFrom: 0.4,
            opacityTo: 0.0,
            stops: [0, 100]
        },
        colors: [POSEIDON_COLORS.accent]
    };
    sparklineTooltip: ApexTooltip = {
        theme: 'dark',
        fixed: {enabled: false},
        x: {show: false},
        y: {title: {formatter: () => 'Cumulative PnL: '}},
        marker: {show: false}
    };

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['timeline'] && this.timeline?.length > 0) {
            this.buildSparkline();
        }
    }

    private buildSparkline(): void {
        const data = this.timeline.map(t => t.cumulative_pnl_usd);
        const isOverallPositive = data[data.length - 1] >= 0;
        const color = isOverallPositive ? POSEIDON_COLORS.success : POSEIDON_COLORS.danger;

        this.sparklineStroke = {...this.sparklineStroke, colors: [color]};
        this.sparklineFill = {...this.sparklineFill, colors: [color]};

        this.sparklineSeries = [{
            name: 'Cumulative PnL',
            data: data as never[]
        }];
    }

    formatUsd(value: number): string {
        if (!value) {
            return '$0.00';
        }
        const absoluteValue = Math.abs(value);
        const sign = value < 0 ? '-' : '+';
        if (absoluteValue >= 1_000_000) {
            return `${sign}$${(absoluteValue / 1_000_000).toFixed(1)}M`;
        }
        if (absoluteValue >= 1_000) {
            return `${sign}$${(absoluteValue / 1_000).toFixed(1)}K`;
        }
        return `${sign}$${absoluteValue.toFixed(2)}`;
    }

    formatDuration(minutes: number): string {
        if (!minutes) {
            return '0m';
        }
        if (minutes >= 1440) {
            return `${(minutes / 1440).toFixed(1)}d`;
        }
        if (minutes >= 60) {
            return `${(minutes / 60).toFixed(1)}h`;
        }
        return `${minutes.toFixed(0)}m`;
    }
}
