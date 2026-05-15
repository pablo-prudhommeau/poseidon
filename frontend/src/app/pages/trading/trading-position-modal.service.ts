import { Injectable, signal } from '@angular/core';

import { TradingEvaluationPayload, TradingPositionPayload } from '../../core/models';

export interface TradingPositionModalRequest {
    position: TradingPositionPayload;
    evaluation?: TradingEvaluationPayload | null;
}

@Injectable({ providedIn: 'root' })
export class TradingPositionModalService {
    public readonly request = signal<TradingPositionModalRequest | null>(null);

    public clear(): void {
        this.request.set(null);
    }

    public open(position: TradingPositionPayload, evaluation: TradingEvaluationPayload | null = null): void {
        this.request.set({ position, evaluation });
    }
}
