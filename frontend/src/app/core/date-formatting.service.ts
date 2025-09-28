import {Inject, Injectable, LOCALE_ID} from '@angular/core';

@Injectable({providedIn: 'root'})
export class DateFormattingService {
    constructor(@Inject(LOCALE_ID) private readonly localeId: string) {}

    public toIsoNoTimezone(value: unknown, timeZone: string = 'Europe/Paris'): string {
        const d = this.coerceToDate(value);
        if (!d) {
            return '';
        }
        const fmt = this.getFormatter(this.localeId, timeZone);
        const parts = fmt.formatToParts(d);
        const get = (type: Intl.DateTimeFormatPartTypes) => parts.find(p => p.type === type)?.value ?? '';
        const yyyy = (get('year') || '').padStart(4, '0');
        const mm = (get('month') || '').padStart(2, '0');
        const dd = (get('day') || '').padStart(2, '0');
        const hh = (get('hour') || '').padStart(2, '0');
        const mi = (get('minute') || '').padStart(2, '0');
        const ss = (get('second') || '').padStart(2, '0');
        return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
    }

    public toIsoNoTimezoneUtc(value: unknown): string {
        return this.toIsoNoTimezone(value, 'UTC');
    }

    private coerceToDate(value: unknown): Date | null {
        if (value instanceof Date) {
            return isNaN(value.getTime()) ? null : value;
        }
        if (value == null) {
            return null;
        }
        if (typeof value === 'number') {
            const ms = value < 1e12 ? value * 1000 : value;
            const d = new Date(ms);
            return isNaN(d.getTime()) ? null : d;
        }
        const str = String(value).trim();
        if (!str) {
            return null;
        }
        const asNum = Number(str);
        const ms = Number.isFinite(asNum) ? (asNum < 1e12 ? asNum * 1000 : asNum) : Date.parse(str);
        const d = new Date(ms);
        return isNaN(d.getTime()) ? null : d;
    }

    private cache = new Map<string, Intl.DateTimeFormat>();

    private getFormatter(locale: string, tz: string): Intl.DateTimeFormat {
        const key = `${locale}|${tz}`;
        const cached = this.cache.get(key);
        if (cached) {
            return cached;
        }
        const fmt = new Intl.DateTimeFormat(locale, {
            timeZone: tz,
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            hour12: false,
        });
        this.cache.set(key, fmt);
        return fmt;
    }
}
