import {inject, Injectable} from '@angular/core';
import {NumberFormattingService} from './number-formatting.service';

@Injectable({
    providedIn: 'root'
})
export class MetricsFormattingService {
    private readonly numberFormattingService = inject(NumberFormattingService);

    public formatMetricLabel(key: string): string {
        return key.toUpperCase()
            .replace(/_USD$/, ' ($)')
            .replace(/_H24$/, ' 24H')
            .replace(/_H6$/, ' 6H')
            .replace(/_H1$/, ' 1H')
            .replace(/_M5$/, ' 5M')
            .replace(/_/g, ' ');
    }

    public formatMetricValue(key: string, value: number | null | undefined): string {
        if (value == null) {
            return '—';
        }
        if (key.includes('percentage') || key.includes('win_rate') || key.includes('change')) {
            return `${this.numberFormattingService.formatNumber(value, 2, 2)}%`;
        }
        if (key.includes('_usd')) {
            return `$${this.numberFormattingService.formatNumber(value, 0, 0)}`;
        }
        if (key.includes('token_age_hours')) {
            return `${this.numberFormattingService.formatNumber(value, 0, 0)}h`;
        }
        if (key.includes('ratio')) {
            return this.numberFormattingService.formatNumber(value, 2, 2);
        }
        if (key.includes('transaction_count') || key.includes('boost')) {
            return this.numberFormattingService.formatNumber(value, 0, 0);
        }
        return this.numberFormattingService.formatNumber(value, 0, 2);
    }
}
