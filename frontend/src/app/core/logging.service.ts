import { Injectable } from '@angular/core';

/**
 * Centralized logging with explicit [TAGS] prefixes.
 * Keep messages short; prefer structured objects for details.
 */
@Injectable({ providedIn: 'root' })
export class LoggingService {
    private buildPrefix(tags: string[]): string {
        return tags.map((t) => `[${t}]`).join('');
    }

    public info(tags: string[], message: string, details?: unknown): void {
        const prefix = this.buildPrefix(tags);
        if (details !== undefined) {
            console.info(`${prefix} ${message}`, details);
            return;
        }
        console.info(`${prefix} ${message}`);
    }

    public verbose(tags: string[], message: string, details?: unknown): void {
        const prefix = this.buildPrefix(tags);
        if (details !== undefined) {
            console.debug(`${prefix} ${message}`, details);
            return;
        }
        console.debug(`${prefix} ${message}`);
    }

    public warn(tags: string[], message: string, details?: unknown): void {
        const prefix = this.buildPrefix(tags);
        if (details !== undefined) {
            console.warn(`${prefix} ${message}`, details);
            return;
        }
        console.warn(`${prefix} ${message}`);
    }

    public error(tags: string[], message: string, details?: unknown): void {
        const prefix = this.buildPrefix(tags);
        if (details !== undefined) {
            console.error(`${prefix} ${message}`, details);
            return;
        }
        console.error(`${prefix} ${message}`);
    }
}
