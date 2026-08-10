import { PositionExitTriggerReason } from '../../core/models';

const EXIT_REASON_LABELS: Partial<Record<PositionExitTriggerReason, string>> = {
    TAKE_PROFIT: 'Take profit',
    STOP_LOSS: 'Stop loss',
    MANUAL: 'Manual',
    KILLED: 'Killed',
    HONEYPOT: 'Honeypot',
    CIRCUIT_BREAKER: 'Circuit breaker',
    WALLET_BALANCE_EMPTY: 'Wallet balance empty'
};

export function formatPositionExitReasonLabel(reason: PositionExitTriggerReason | string | null | undefined): string {
    if (reason == null || reason === '') {
        return '—';
    }
    const mappedLabel = EXIT_REASON_LABELS[reason as PositionExitTriggerReason];
    if (mappedLabel != null) {
        return mappedLabel;
    }
    return String(reason);
}
