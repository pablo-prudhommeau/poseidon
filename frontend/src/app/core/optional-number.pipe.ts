import { formatNumber } from '@angular/common';
import { inject, LOCALE_ID, Pipe, PipeTransform } from '@angular/core';

@Pipe({
    name: 'optionalNumber',
    standalone: true
})
export class OptionalNumberPipe implements PipeTransform {
    private readonly locale = inject(LOCALE_ID);

    transform(value: number | null | undefined, digitsInfo: string = '1.2-2', prefix: string = '', suffix: string = ''): string {
        if (value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))) {
            return '—';
        }
        return `${prefix}${formatNumber(value, this.locale, digitsInfo)}${suffix}`;
    }
}
