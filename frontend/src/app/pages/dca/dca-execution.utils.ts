import { DcaOrderPayload, DcaStrategyPayload } from '../../core/models';

export function hasExecutedDcaOrders(strategy: DcaStrategyPayload): boolean {
    const executionOrders: DcaOrderPayload[] = strategy.execution_orders ?? [];
    return executionOrders.some((executionOrder: DcaOrderPayload) => executionOrder.order_status === 'EXECUTED');
}
