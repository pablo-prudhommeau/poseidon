import {Inject, Injectable, LOCALE_ID} from '@angular/core';

@Injectable({providedIn: 'root'})
export class DatetimeDisplayService {
    private readonly shortFormatter: Intl.DateTimeFormat;

    constructor(@Inject(LOCALE_ID) private readonly localeId: string) {
        this.shortFormatter = new Intl.DateTimeFormat(this.localeId, {
            day: 'numeric',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
    }

    parseToDate(value: unknown): Date | null {
        if (value == null) {
            return null;
        }
        if (value instanceof Date) {
            return Number.isNaN(value.getTime()) ? null : value;
        }
        if (typeof value === 'number' && Number.isFinite(value)) {
            const fromNumber = new Date(value);
            return Number.isNaN(fromNumber.getTime()) ? null : fromNumber;
        }
        if (typeof value === 'string' && value.trim().length > 0) {
            const parsed = new Date(value);
            return Number.isNaN(parsed.getTime()) ? null : parsed;
        }
        return null;
    }

    formatShortForGrid(value: unknown): string {
        const date = this.parseToDate(value);
        if (date === null) {
            return '';
        }
        return this.shortFormatter.format(date);
    }

    formatIsoForTooltip(value: unknown): string {
        const date = this.parseToDate(value);
        if (date === null) {
            return '';
        }
        return date.toISOString();
    }
}
