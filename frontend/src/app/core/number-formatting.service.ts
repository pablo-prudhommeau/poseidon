import {Inject, Injectable, LOCALE_ID} from '@angular/core';

@Injectable({providedIn: 'root'})
export class NumberFormattingService {
    constructor(@Inject(LOCALE_ID) private readonly localeId: string) {}

    formatNumber(value: unknown, min: number, max: number): string {
        const number = this.toNumberSafe(value);
        if (number === null) {
            return '';
        }
        return new Intl.NumberFormat('en-US', {
            minimumFractionDigits: min,
            maximumFractionDigits: max
        }).format(number);
    }

    formatCurrency(value: unknown, currency: string, min: number, max: number): string {
        const number = this.toNumberSafe(value);
        if (number === null) {
            return '';
        }
        return new Intl.NumberFormat(this.localeId, {
            style: 'currency',
            currency,
            minimumFractionDigits: min,
            maximumFractionDigits: max
        }).format(number);
    }

    toNumberSafe(value: unknown): number | null {
        if (value == null) {
            return null;
        }
        const n = Number(value);
        return Number.isFinite(n) ? n : null;
    }
}