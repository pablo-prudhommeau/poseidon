import {CurrencyPipe, DatePipe, DecimalPipe, NgClass} from '@angular/common';
import {Component, computed, input} from '@angular/core';
import {CardModule} from 'primeng/card';
import {PopoverModule} from 'primeng/popover';
import {DcaOrderPayload, DcaStrategyPayload, OrderDueDateMarker, TimelineNode} from '../../../core/models';

const PROCESSING_STATUS_LIST: string[] = ['WAITING_USER_APPROVAL', 'APPROVED', 'WITHDRAWN_FROM_AAVE', 'SWAPPED', 'PROCESSING'];

@Component({
    standalone: true,
    selector: 'app-dca-strategy-execution-timeline',
    imports: [DatePipe, DecimalPipe, NgClass, CurrencyPipe, CardModule, PopoverModule],
    templateUrl: './dca-strategy-execution-timeline.component.html',
    styleUrls: ['./dca-strategy-execution-timeline.component.css']
})
export class DcaStrategyExecutionTimelineComponent {
    public strategy = input.required<DcaStrategyPayload>();

    public readonly lastNonPendingOrderTimestamp = computed<number | null>(() => {
        const strategyEntity = this.strategy();
        if (!strategyEntity.execution_orders || strategyEntity.execution_orders.length === 0) {
            return null;
        }

        const sortedOrders = [...strategyEntity.execution_orders].sort(
            (orderA, orderB) => new Date(orderA.planned_execution_date).getTime() - new Date(orderB.planned_execution_date).getTime()
        );

        let lastNonPendingTimestamp: number | null = null;
        for (const order of sortedOrders) {
            if (order.order_status !== 'PENDING') {
                lastNonPendingTimestamp = new Date(order.planned_execution_date).getTime();
            }
        }

        return lastNonPendingTimestamp;
    });

    public readonly timelineNodes = computed<TimelineNode[]>(() => {
        const strategyEntity = this.strategy();
        if (!strategyEntity.execution_orders || strategyEntity.execution_orders.length === 0) {
            return [];
        }

        const startTimestamp = new Date(strategyEntity.strategy_start_date).getTime();
        const endTimestamp = new Date(strategyEntity.strategy_end_date).getTime();
        const totalDuration = endTimestamp - startTimestamp;

        if (totalDuration <= 0) {
            return [];
        }

        const allOrders = [...strategyEntity.execution_orders].sort(
            (orderA, orderB) => new Date(orderA.planned_execution_date).getTime() - new Date(orderB.planned_execution_date).getTime()
        );

        const rulerNodes = this.generateCalendarRulerNodes(startTimestamp, endTimestamp, totalDuration);

        const nodesByIdentifier = new Map<string, TimelineNode>(rulerNodes.map((node) => [node.identifier, { ...node, orders: [] as DcaOrderPayload[] }]));

        for (const order of allOrders) {
            const orderTimestamp = new Date(order.planned_execution_date).getTime();
            const targetNode = this.findContainingPeriodNode(rulerNodes, orderTimestamp);
            nodesByIdentifier.get(targetNode.identifier)?.orders.push(order);
        }

        const nodesWithOrders = rulerNodes
            .filter((node) => {
                const nodeWithOrders = nodesByIdentifier.get(node.identifier)!;
                return nodeWithOrders.isProcessing || nodeWithOrders.orders.length > 0 || node.isMonthBoundary || node.isMinor;
            })
            .map((node) => ({
                ...nodesByIdentifier.get(node.identifier)!,
                orders: nodesByIdentifier.get(node.identifier)!.orders
            }));

        const frontier = this.lastNonPendingOrderTimestamp() ?? 0;

        return nodesWithOrders.map((node, index) => {
            const enriched = this.enrichTimelineNode(node);
            const isBeforeFrontier = node.timestamp <= frontier;
            const leftPositionPercent = nodesWithOrders.length > 1 ? (index / (nodesWithOrders.length - 1)) * 100 : 0;

            const previousNode = index > 0 ? nodesWithOrders[index - 1] : null;
            enriched.periodStartDate = previousNode ? previousNode.timestamp : node.timestamp;

            const startLabel = new Date(enriched.periodStartDate).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric'
            });
            const endLabel = new Date(node.timestamp).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric'
            });
            enriched.periodLabel = enriched.periodStartDate === node.timestamp ? endLabel : `${startLabel} - ${endLabel}`;

            if (isBeforeFrontier) {
                const previousOrders = allOrders.filter((o) => new Date(o.planned_execution_date).getTime() <= node.timestamp);
                if (previousOrders.length > 0) {
                    enriched.representativeStatus = this.calculateSyntheticStatus(previousOrders);
                } else if (enriched.orders.length === 0) {
                    enriched.representativeStatus = 'PENDING';
                }
            } else {
                enriched.representativeStatus = 'PENDING';
            }

            return { ...enriched, leftPositionPercent };
        });
    });

    public readonly currentProgressPercent = computed(() => {
        const nodes = this.timelineNodes();
        const frontier = this.lastNonPendingOrderTimestamp();

        if (nodes.length < 2 || frontier === null) {
            return 0;
        }

        let latestActiveIndex = 0;
        for (let i = 0; i < nodes.length; i++) {
            if (nodes[i].timestamp <= frontier) {
                latestActiveIndex = i;
            }
        }

        return (latestActiveIndex / (nodes.length - 1)) * 100;
    });

    public readonly orderDueDateMarkers = computed<OrderDueDateMarker[]>(() => {
        const strategyEntity = this.strategy();
        const nodes = this.timelineNodes();
        if (nodes.length === 0 || !strategyEntity.execution_orders) {
            return [];
        }

        return strategyEntity.execution_orders.map((order) => {
            const orderTimestamp = new Date(order.planned_execution_date).getTime();

            let segmentStartIndex = 0;
            let segmentEndIndex = 0;

            for (let i = 0; i < nodes.length; i++) {
                if (orderTimestamp <= nodes[i].timestamp) {
                    segmentEndIndex = i;
                    segmentStartIndex = Math.max(0, i - 1);
                    break;
                }
            }

            const startNode = nodes[segmentStartIndex];
            const endNode = nodes[segmentEndIndex];

            let position = endNode.leftPositionPercent;
            if (startNode !== endNode) {
                const timeInSegment = orderTimestamp - startNode.timestamp;
                const totalSegmentTime = endNode.timestamp - startNode.timestamp;
                const fraction = Math.max(0, Math.min(1, timeInSegment / totalSegmentTime));
                position = startNode.leftPositionPercent + (endNode.leftPositionPercent - startNode.leftPositionPercent) * fraction;
            }

            return {
                leftPositionPercent: position,
                status: order.order_status
            };
        });
    });

    public readonly progressGradientClass = computed(() => {
        const nodes = this.timelineNodes();
        const activeNodes = nodes.filter((node) => node.representativeStatus !== 'PENDING' || node.isProcessing);
        if (activeNodes.length === 0) {
            return 'from-slate-600 to-transparent';
        }

        const lastActiveNode = activeNodes[activeNodes.length - 1];
        const status = lastActiveNode.representativeStatus;

        const hasHistory = activeNodes.some((node) => ['EXECUTED', 'SKIPPED', 'REJECTED'].includes(node.representativeStatus));
        const startColor = hasHistory ? 'emerald-500' : status === 'PENDING' ? 'slate-600' : 'blue-500';

        if (PROCESSING_STATUS_LIST.includes(status)) {
            return `from-${startColor} via-blue-500 to-blue-400`;
        }
        if (status === 'EXECUTED') {
            return `from-${startColor} to-emerald-400`;
        }
        if (status === 'FAILED' || status === 'REJECTED') {
            return `from-${startColor} via-rose-500 to-rose-400`;
        }
        if (status === 'SKIPPED') {
            return `from-${startColor} via-amber-500 to-amber-400`;
        }
        return `from-${startColor} to-transparent`;
    });

    public isProtectedByPurchasePriceGuard(order: DcaOrderPayload): boolean {
        return (
            order.transaction_hash === 'AVERAGE_PRICE_PROTECTION_BYPASS' ||
            (order.allocation_decision_description?.includes('AVERAGE_PRICE_PROTECTION') ?? false)
        );
    }

    public resolveAllocationDecisionColor(allocationDecision: string): string {
        if (allocationDecision.includes('AGGRESSIVE_DIP_ACCUMULATION')) {
            return 'text-emerald-400';
        }
        if (allocationDecision.includes('CONSERVATIVE_RETENTION')) {
            return 'text-amber-400';
        }
        if (allocationDecision.includes('FINAL_FULL_DEPLOYMENT')) {
            return 'text-purple-400';
        }
        if (allocationDecision.includes('AVERAGE_PRICE_PROTECTION')) {
            return 'text-rose-400';
        }
        return 'text-slate-400';
    }

    public resolveAllocationDecisionLabel(allocationDecision: string): string {
        if (allocationDecision.includes('AGGRESSIVE_DIP_ACCUMULATION')) {
            return 'Aggressive Accumulation';
        }
        if (allocationDecision.includes('CONSERVATIVE_RETENTION')) {
            return 'Conservative Retention';
        }
        if (allocationDecision.includes('FINAL_FULL_DEPLOYMENT')) {
            return 'Final Deployment';
        }
        if (allocationDecision.includes('FALLBACK_NOMINAL')) {
            return 'Nominal Strategy';
        }
        if (allocationDecision.includes('AVERAGE_PRICE_PROTECTION')) {
            return 'PRU Protection Halt';
        }
        return allocationDecision;
    }

    private calculateSyntheticStatus(orders: DcaOrderPayload[]): string {
        if (orders.some((o) => PROCESSING_STATUS_LIST.includes(o.order_status))) {
            return 'PROCESSING';
        }
        if (orders.some((o) => o.order_status === 'REJECTED' || o.order_status === 'FAILED')) {
            return 'REJECTED';
        }
        if (orders.some((o) => o.order_status === 'EXECUTED')) {
            return 'EXECUTED';
        }
        if (orders.some((o) => o.order_status === 'SKIPPED')) {
            return 'SKIPPED';
        }
        return 'PENDING';
    }

    private createTimelineNode(
        partial: Partial<TimelineNode> & {
            identifier: string;
            timestamp: number;
            leftPositionPercent: number;
            label: string;
        }
    ): TimelineNode {
        return {
            identifier: partial.identifier,
            timestamp: partial.timestamp,
            leftPositionPercent: partial.leftPositionPercent,
            isMajor: partial.isMajor ?? false,
            isMinor: partial.isMinor ?? false,
            isMonthBoundary: partial.isMonthBoundary ?? false,
            isProcessing: false,
            orders: [],
            label: partial.label,
            representativeStatus: 'PENDING',
            totalPlannedAmount: 0,
            totalExecutedAmount: 0,
            totalAcquiredTargetAssetAmount: 0,
            protectedOrderCount: 0,
            skippedOrderCount: 0,
            plannedExecutionDate: new Date(partial.timestamp).toISOString(),
            periodLabel: '',
            periodStartDate: null
        };
    }

    private enrichTimelineNode(node: TimelineNode): TimelineNode {
        const totalPlannedAmount = node.orders.reduce((sum, order) => sum + (order.planned_source_asset_amount || 0), 0);
        const executedOrders = node.orders.filter((order) => order.order_status === 'EXECUTED');
        const totalExecutedAmount = executedOrders.reduce((sum, order) => sum + (order.executed_source_asset_amount || 0), 0);
        const totalAcquiredTargetAssetAmount = executedOrders.reduce((sum, order) => sum + (order.executed_target_asset_amount || 0), 0);
        const protectedOrderCount = node.orders.filter((order) => this.isProtectedByPurchasePriceGuard(order)).length;
        const skippedOrderCount = node.orders.filter((order) => order.order_status === 'SKIPPED').length;

        const representativeStatus = this.calculateSyntheticStatus(node.orders);

        return {
            ...node,
            representativeStatus,
            isProcessing: PROCESSING_STATUS_LIST.includes(representativeStatus),
            totalPlannedAmount,
            totalExecutedAmount,
            totalAcquiredTargetAssetAmount,
            protectedOrderCount,
            skippedOrderCount,
            plannedExecutionDate: new Date(node.timestamp).toISOString()
        };
    }

    private findContainingPeriodNode(sortedRulerNodes: TimelineNode[], orderTimestamp: number): TimelineNode {
        for (const node of sortedRulerNodes) {
            if (orderTimestamp <= node.timestamp) {
                return node;
            }
        }
        return sortedRulerNodes[sortedRulerNodes.length - 1];
    }

    private generateCalendarRulerNodes(startTimestamp: number, endTimestamp: number, totalDuration: number): TimelineNode[] {
        const rulerNodes: TimelineNode[] = [];
        const startDate = new Date(startTimestamp);
        const endDate = new Date(endTimestamp);

        rulerNodes.push(
            this.createTimelineNode({
                identifier: 'strategy-start',
                timestamp: startTimestamp,
                leftPositionPercent: 0,
                isMajor: startDate.getDate() === 1,
                isMinor: startDate.getDate() !== 1,
                isMonthBoundary: startDate.getDate() === 1,
                label:
                    startDate.getDate() === 1
                        ? startDate.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
                        : startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            })
        );

        let currentMonthPointer = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 1);

        while (currentMonthPointer.getTime() < endTimestamp) {
            const monthTimestamp = currentMonthPointer.getTime();
            const monthLeftPosition = ((monthTimestamp - startTimestamp) / totalDuration) * 100;
            const monthLabel = currentMonthPointer.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });

            rulerNodes.push(
                this.createTimelineNode({
                    identifier: `month-${currentMonthPointer.getFullYear()}-${currentMonthPointer.getMonth()}`,
                    timestamp: monthTimestamp,
                    leftPositionPercent: monthLeftPosition,
                    isMajor: true,
                    isMinor: false,
                    isMonthBoundary: true,
                    label: monthLabel
                })
            );

            currentMonthPointer = new Date(currentMonthPointer.getFullYear(), currentMonthPointer.getMonth() + 1, 1);
        }

        if (!rulerNodes.some((n) => n.timestamp === endTimestamp)) {
            rulerNodes.push(
                this.createTimelineNode({
                    identifier: 'strategy-end',
                    timestamp: endTimestamp,
                    leftPositionPercent: 100,
                    isMajor: endDate.getDate() === 1,
                    isMinor: endDate.getDate() !== 1,
                    isMonthBoundary: endDate.getDate() === 1,
                    label: endDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                })
            );
        }

        const sortedNodes = [...rulerNodes].sort((a, b) => a.timestamp - b.timestamp);
        const finalNodes: TimelineNode[] = [];

        for (let i = 0; i < sortedNodes.length - 1; i++) {
            const current = sortedNodes[i];
            const next = sortedNodes[i + 1];
            finalNodes.push(current);

            const durationSegment = next.timestamp - current.timestamp;
            if (durationSegment > 10 * 24 * 60 * 60 * 1000) {
                const currentMonth = new Date(current.timestamp).getMonth();
                const nextMonth = new Date(next.timestamp).getMonth();
                const isSameMonth = currentMonth === nextMonth;

                const startWeek = Math.min(4, Math.floor(new Date(current.timestamp).getDate() / 7) + 1);
                const endWeek = isSameMonth ? Math.min(4, Math.floor(new Date(next.timestamp).getDate() / 7) + 1) : 5;

                const missingWeeks: number[] = [];
                for (let w = startWeek + 1; w < endWeek; w++) {
                    missingWeeks.push(w);
                }

                if (missingWeeks.length > 0) {
                    missingWeeks.forEach((_, index) => {
                        const fraction = (index + 1) / (missingWeeks.length + 1);
                        const timestamp = current.timestamp + durationSegment * fraction;
                        const date = new Date(timestamp);
                        const weekNumber = this.getIsoWeekNumber(date);

                        finalNodes.push(
                            this.createTimelineNode({
                                identifier: `week-${date.getFullYear()}-w${weekNumber}`,
                                timestamp,
                                leftPositionPercent: current.leftPositionPercent + (next.leftPositionPercent - current.leftPositionPercent) * fraction,
                                isMajor: false,
                                isMinor: true,
                                label: `W.${weekNumber}`
                            })
                        );
                    });
                }
            }
        }

        finalNodes.push(sortedNodes[sortedNodes.length - 1]);

        finalNodes.sort((a, b) => a.timestamp - b.timestamp);
        return finalNodes;
    }

    private getIsoWeekNumber(date: Date): number {
        const tempDate = new Date(date.getTime());
        tempDate.setHours(0, 0, 0, 0);
        tempDate.setDate(tempDate.getDate() + 3 - ((tempDate.getDay() + 6) % 7));
        const week1 = new Date(tempDate.getFullYear(), 0, 4);
        return 1 + Math.round(((tempDate.getTime() - week1.getTime()) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
    }
}
