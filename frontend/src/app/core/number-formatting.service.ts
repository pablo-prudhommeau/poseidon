import { Inject, Injectable, LOCALE_ID } from '@angular/core';

const SUBSCRIPT_DIGITS = ['₀', '₁', '₂', '₃', '₄', '₅', '₆', '₇', '₈', '₉'] as const;

@Injectable({ providedIn: 'root' })
export class NumberFormattingService {
    constructor(@Inject(LOCALE_ID) private readonly localeId: string) {}

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

    formatNumberCompactForGrid(value: unknown, minimumLeadingZeroRun: number = 4): string {
        const number = this.toNumberSafe(value);
        if (number === null) {
            return '';
        }
        if (number === 0) {
            return '0';
        }
        const sign = number < 0 ? '-' : '';
        const abs = Math.abs(number);
        if (abs >= 1) {
            return sign + this.formatNumber(abs, 2, 6);
        }
        const compact = this.formatPositiveFractionalWithLeadingZeroSubscript(abs, minimumLeadingZeroRun);
        if (compact === null) {
            return sign + this.formatNumber(abs, 2, 8);
        }
        return sign + compact;
    }

    formatQuantityHumanReadable(value: unknown): string {
        const number = this.toNumberSafe(value);
        if (number === null) {
            return '';
        }
        if (number === 0) {
            return '0';
        }
        return new Intl.NumberFormat(this.localeId, {
            notation: 'compact',
            maximumFractionDigits: 2,
            minimumFractionDigits: 0
        }).format(number);
    }

    formatUsdCompactForGrid(value: unknown, minimumLeadingZeroRun: number = 4): string {
        const number = this.toNumberSafe(value);
        if (number === null) {
            return '';
        }
        if (number === 0) {
            return '$0';
        }
        const sign = number < 0 ? '-' : '';
        const abs = Math.abs(number);
        if (abs >= 1) {
            return sign + this.formatCurrency(abs, 'USD', 2, 4);
        }
        const compact = this.formatPositiveFractionalWithLeadingZeroSubscript(abs, minimumLeadingZeroRun);
        if (compact === null) {
            return sign + this.formatCurrency(abs, 'USD', 4, 8);
        }
        return sign + '$' + compact;
    }

    toNumberSafe(value: unknown): number | null {
        if (value == null) {
            return null;
        }
        const n = Number(value);
        return Number.isFinite(n) ? n : null;
    }

    private formatPositiveFractionalWithLeadingZeroSubscript(positiveFraction: number, minimumLeadingZeroRun: number): string | null {
        if (positiveFraction <= 0 || positiveFraction >= 1) {
            return null;
        }
        const normalized = positiveFraction.toFixed(24).replace(/(\.\d*?)0+$/, '$1');
        const match = /^0\.(0+)([1-9]\d*)$/.exec(normalized);
        if (!match) {
            return null;
        }
        const zeroRun = match[1].length;
        let tail = match[2];
        if (zeroRun < minimumLeadingZeroRun) {
            return null;
        }
        tail = tail.slice(0, 5);
        if (tail.length === 0) {
            return null;
        }
        const subscriptIndex = zeroRun - 1;
        if (subscriptIndex <= 0 || subscriptIndex > 9) {
            return `0.0${SUBSCRIPT_DIGITS[9]}₊${tail}`;
        }
        return `0.0${SUBSCRIPT_DIGITS[subscriptIndex]}${tail}`;
    }
}
