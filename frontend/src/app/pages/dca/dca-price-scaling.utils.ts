import { DcaOrderPayload, DcaStrategyPayload } from '../../core/models';

function resolveExecutedOrdersChronologically(executionOrders: DcaOrderPayload[]): DcaOrderPayload[] {
    return executionOrders
        .filter(
            (executionOrder: DcaOrderPayload) =>
                executionOrder.order_status === 'EXECUTED' &&
                executionOrder.executed_at !== null &&
                executionOrder.executed_at !== undefined &&
                executionOrder.actual_execution_price !== null &&
                executionOrder.actual_execution_price !== undefined
        )
        .sort(
            (orderA: DcaOrderPayload, orderB: DcaOrderPayload) =>
                new Date(orderA.executed_at as string).getTime() - new Date(orderB.executed_at as string).getTime()
        );
}

export function resolveHistoricalBacktestStartExecutionPrice(strategy: DcaStrategyPayload): number {
    return strategy.historical_backtest_payload?.dumb_dca_series?.[0]?.execution_price ?? 0;
}

export function resolveFirstExecutedOrderMarketPrice(strategy: DcaStrategyPayload): number {
    const executedOrders: DcaOrderPayload[] = resolveExecutedOrdersChronologically(strategy.execution_orders ?? []);
    if (executedOrders.length === 0) {
        return 0;
    }
    return executedOrders[0].actual_execution_price ?? 0;
}

export function resolveProjectedLivePriceMultiplier(strategy: DcaStrategyPayload): number {
    const historicalStartExecutionPrice: number = resolveHistoricalBacktestStartExecutionPrice(strategy);
    const firstExecutedOrderMarketPrice: number = resolveFirstExecutedOrderMarketPrice(strategy);
    if (firstExecutedOrderMarketPrice > 0 && historicalStartExecutionPrice > 0) {
        return firstExecutedOrderMarketPrice / historicalStartExecutionPrice;
    }
    return 1;
}
