import { PositionExitTriggerReason } from '../../core/models';

const EXIT_REASON_LABELS: Partial<Record<PositionExitTriggerReason, string>> = {
    TAKE_PROFIT_1: 'Take profit 1',
    TAKE_PROFIT_2: 'Take profit 2',
    STOP_LOSS: 'Stop loss',
    MANUAL: 'Manual close',
    KILLED: 'Killed',
    FROZEN_ACCOUNT: 'Frozen account',
    CIRCUIT_BREAKER: 'Circuit breaker',
    WALLET_BALANCE_EMPTY: 'Wallet balance empty'
};

export function formatPositionExitReasonLabel(reason: PositionExitTriggerReason | string | null | undefined): string {
    if (!reason) {
        return '—';
    }
    const mappedLabel = EXIT_REASON_LABELS[reason as PositionExitTriggerReason];
    if (mappedLabel) {
        return mappedLabel;
    }
    return reason.replaceAll('_', ' ');
}
