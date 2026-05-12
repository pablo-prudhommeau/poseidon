import {Injectable, signal} from '@angular/core';

import {TradingPositionPayload} from '../../core/models';

@Injectable({providedIn: 'root'})
export class TradingPositionModalService {
    public readonly requestedPosition = signal<TradingPositionPayload | null>(null);

    public open(position: TradingPositionPayload): void {
        this.requestedPosition.set(position);
    }

    public clear(): void {
        this.requestedPosition.set(null);
    }
}
