import { DcaOrderPayload, DcaStrategyPayload } from '../../core/models';

export function hasExecutedDcaOrders(strategy: DcaStrategyPayload): boolean {
    const executionOrders: DcaOrderPayload[] = strategy.execution_orders ?? [];
    return executionOrders.some(
        (executionOrder: DcaOrderPayload) => executionOrder.order_status === 'EXECUTED' && (executionOrder.executed_source_asset_amount ?? 0) > 0
    );
}

export function normalizeEvmTransactionHash(transactionHash: string): string {
    const trimmedTransactionHash = transactionHash.trim();
    if (!trimmedTransactionHash) {
        return trimmedTransactionHash;
    }
    return trimmedTransactionHash.startsWith('0x') ? trimmedTransactionHash : `0x${trimmedTransactionHash}`;
}
