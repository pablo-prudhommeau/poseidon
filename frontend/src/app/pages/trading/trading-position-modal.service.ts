import { Injectable, signal } from '@angular/core';

import { TradingPositionPayload } from '../../core/models';

@Injectable({ providedIn: 'root' })
export class TradingPositionModalService {
    public readonly requestedPosition = signal<TradingPositionPayload | null>(null);

    public clear(): void {
        this.requestedPosition.set(null);
    }

    public open(position: TradingPositionPayload): void {
        this.requestedPosition.set(position);
    }
}
