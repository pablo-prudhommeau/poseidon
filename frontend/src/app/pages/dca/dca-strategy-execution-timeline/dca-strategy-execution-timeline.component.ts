import { CurrencyPipe, DatePipe, DecimalPipe, NgClass } from '@angular/common';
import { Component, computed, input } from '@angular/core';
import { CardModule } from 'primeng/card';
import { PopoverModule } from 'primeng/popover';
import { DcaAllocationDecision, DcaOrderPayload, DcaStrategyPayload, OrderDueDateMarker, TimelineNode } from '../../../core/models';
import { normalizeEvmTransactionHash } from '../dca-execution.utils';

const PROCESSING_STATUS_LIST: string[] = ['WAITING_USER_APPROVAL', 'AWAITING_WITHDRAW', 'AWAITING_SWAP', 'AWAITING_SUPPLY', 'PROCESSING'];

const TERMINAL_FAILURE_STATUS_LIST: string[] = ['FAILED', 'REJECTED', 'SUSPENDED'];

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

        const lastOrderTimestamp = new Date(allOrders[allOrders.length - 1].planned_execution_date).getTime();
        const strategyEndAnchorTimestamp = Math.max(startTimestamp, Math.min(endTimestamp, lastOrderTimestamp));

        const rulerNodes = this.generateCalendarRulerNodes(startTimestamp, endTimestamp, totalDuration, strategyEndAnchorTimestamp);

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
                const previousOrders = allOrders.filter((order) => new Date(order.planned_execution_date).getTime() <= node.timestamp);
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
        for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
            if (nodes[nodeIndex].timestamp <= frontier) {
                latestActiveIndex = nodeIndex;
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

        const sortedOrders = [...strategyEntity.execution_orders].sort(
            (orderA, orderB) => new Date(orderA.planned_execution_date).getTime() - new Date(orderB.planned_execution_date).getTime()
        );

        const strategyStartNode = nodes.find((node) => node.identifier === 'strategy-start');
        const strategyEndNode = nodes.find((node) => node.identifier === 'strategy-end');

        return sortedOrders.map((order, orderIndex) => {
            const orderTimestamp = new Date(order.planned_execution_date).getTime();
            const isFirstOrder = orderIndex === 0;
            const isLastOrder = orderIndex === sortedOrders.length - 1;

            if (isLastOrder && strategyEndNode) {
                return {
                    orderId: order.id,
                    leftPositionPercent: strategyEndNode.leftPositionPercent,
                    status: this.resolveOrderVisualStatus(order),
                    anchorsMajorNode: true
                };
            }

            if (isFirstOrder && strategyStartNode) {
                return {
                    orderId: order.id,
                    leftPositionPercent: strategyStartNode.leftPositionPercent,
                    status: this.resolveOrderVisualStatus(order),
                    anchorsMajorNode: true
                };
            }

            let segmentStartIndex = 0;
            let segmentEndIndex = 0;

            for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex++) {
                if (orderTimestamp <= nodes[nodeIndex].timestamp) {
                    segmentEndIndex = nodeIndex;
                    segmentStartIndex = Math.max(0, nodeIndex - 1);
                    break;
                }
            }

            const startNode = nodes[segmentStartIndex];
            const endNode = nodes[segmentEndIndex];

            let position = endNode.leftPositionPercent;
            if (startNode !== endNode) {
                const timeInSegment = orderTimestamp - startNode.timestamp;
                const totalSegmentTime = endNode.timestamp - startNode.timestamp;
                const fraction = totalSegmentTime > 0 ? Math.max(0, Math.min(1, timeInSegment / totalSegmentTime)) : 0;
                position = startNode.leftPositionPercent + (endNode.leftPositionPercent - startNode.leftPositionPercent) * fraction;
            }

            return {
                orderId: order.id,
                leftPositionPercent: position,
                status: this.resolveOrderVisualStatus(order),
                anchorsMajorNode: false
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

        const hasHistory = activeNodes.some((node) => ['EXECUTED', 'SKIPPED', 'REJECTED', 'SUSPENDED'].includes(node.representativeStatus));
        const startColor = hasHistory ? 'emerald-500' : status === 'PENDING' ? 'slate-600' : 'blue-500';

        if (PROCESSING_STATUS_LIST.includes(status)) {
            return `from-${startColor} via-blue-500 to-blue-400`;
        }
        if (status === 'EXECUTED') {
            return `from-${startColor} to-emerald-400`;
        }
        if (TERMINAL_FAILURE_STATUS_LIST.includes(status)) {
            return `from-${startColor} via-rose-500 to-rose-400`;
        }
        if (status === 'SKIPPED') {
            return `from-${startColor} via-amber-500 to-amber-400`;
        }
        return `from-${startColor} to-transparent`;
    });

    public async copyToClipboard(value: string | undefined | null): Promise<void> {
        if (!value) {
            return;
        }
        try {
            await navigator.clipboard.writeText(normalizeEvmTransactionHash(value));
        } catch {
            return;
        }
    }

    public formatTransactionHashPreview(transactionHash: string): string {
        const normalizedTransactionHash = normalizeEvmTransactionHash(transactionHash);
        if (normalizedTransactionHash.length <= 36) {
            return normalizedTransactionHash;
        }
        return `${normalizedTransactionHash.slice(0, 22)}...${normalizedTransactionHash.slice(-12)}`;
    }

    public isPrimaryMajorNode(timelineNode: TimelineNode): boolean {
        return timelineNode.identifier.startsWith('month-') || (timelineNode.identifier === 'strategy-start' && timelineNode.isMonthBoundary);
    }

    public isProtectedByPurchasePriceGuard(order: DcaOrderPayload): boolean {
        return order.allocation_decision === 'AVERAGE_PRICE_PROTECTION_HALT';
    }

    public isSecondaryMajorNode(timelineNode: TimelineNode): boolean {
        return (
            (timelineNode.identifier === 'strategy-start' && !timelineNode.isMonthBoundary) ||
            timelineNode.identifier === 'strategy-end' ||
            timelineNode.identifier.startsWith('week-')
        );
    }

    public isTerminalFailureStatus(status: string): boolean {
        return TERMINAL_FAILURE_STATUS_LIST.includes(status);
    }

    public resolveAllocationDecisionColor(allocationDecision: DcaAllocationDecision): string {
        if (allocationDecision === 'AGGRESSIVE_DIP_ACCUMULATION_SCALED') {
            return 'text-emerald-400';
        }
        if (allocationDecision === 'CONSERVATIVE_RETENTION_SCALED') {
            return 'text-amber-400';
        }
        if (allocationDecision === 'FALLBACK_NOMINAL_STRATEGY') {
            return 'text-slate-400';
        }
        if (allocationDecision === 'AVERAGE_PRICE_PROTECTION_HALT') {
            return 'text-rose-400';
        }
        return 'text-slate-400';
    }

    public resolveAllocationDecisionLabel(allocationDecision: DcaAllocationDecision, allocationMultiplier?: number | null): string {
        if (allocationDecision === 'AGGRESSIVE_DIP_ACCUMULATION_SCALED') {
            return allocationMultiplier && allocationMultiplier !== 1
                ? `Aggressive accumulation (×${allocationMultiplier.toFixed(2)})`
                : 'Aggressive accumulation';
        }
        if (allocationDecision === 'CONSERVATIVE_RETENTION_SCALED') {
            return allocationMultiplier && allocationMultiplier !== 1
                ? `Conservative retention (×${allocationMultiplier.toFixed(2)})`
                : 'Conservative retention';
        }
        if (allocationDecision === 'FALLBACK_NOMINAL_STRATEGY') {
            return allocationMultiplier && allocationMultiplier !== 1 ? `Nominal strategy (×${allocationMultiplier.toFixed(2)})` : 'Nominal strategy';
        }
        if (allocationDecision === 'AVERAGE_PRICE_PROTECTION_HALT') {
            return 'PRU protection halt';
        }
        return allocationDecision;
    }

    public resolveNodeCircleClasses(timelineNode: TimelineNode): Record<string, boolean> {
        const status = timelineNode.representativeStatus;
        const isProcessing = timelineNode.isProcessing || PROCESSING_STATUS_LIST.includes(status);
        const circleClasses: Record<string, boolean> = this.isPrimaryMajorNode(timelineNode) ? { 'h-4 w-4 border-2': true } : { 'h-2.5 w-2.5 border': true };

        if (isProcessing) {
            circleClasses['border-blue-500 bg-blue-500/30 shadow-blue-500/30'] = true;
            return circleClasses;
        }
        if (status === 'EXECUTED') {
            circleClasses['border-emerald-500 bg-emerald-500/20 shadow-emerald-500/20'] = true;
            return circleClasses;
        }
        if (this.isTerminalFailureStatus(status)) {
            circleClasses['border-rose-500 bg-rose-500/20 shadow-rose-500/20'] = true;
            return circleClasses;
        }
        if (status === 'SKIPPED' || status === 'WAITING_USER_APPROVAL') {
            circleClasses['border-amber-500 bg-amber-500/10'] = true;
            return circleClasses;
        }
        if (this.isPrimaryMajorNode(timelineNode)) {
            circleClasses['border-slate-400 bg-slate-800/20'] = true;
            return circleClasses;
        }
        circleClasses['border-slate-500 bg-slate-900/30'] = true;
        return circleClasses;
    }

    public resolveNodeLabelClasses(timelineNode: TimelineNode): Record<string, boolean> {
        const status = timelineNode.representativeStatus;
        const isProcessing = timelineNode.isProcessing || PROCESSING_STATUS_LIST.includes(status);

        if (isProcessing) {
            return { 'text-blue-500': true };
        }
        if (status === 'EXECUTED') {
            return { 'text-emerald-500': true };
        }
        if (this.isTerminalFailureStatus(status)) {
            return { 'text-rose-500': true };
        }
        if (status === 'SKIPPED' || status === 'WAITING_USER_APPROVAL') {
            return { 'text-amber-500': true };
        }
        if (this.isPrimaryMajorNode(timelineNode)) {
            return { 'text-slate-400': true };
        }
        return { 'text-slate-500': true };
    }

    public resolveOrderMarkerClasses(status: string): Record<string, boolean> {
        if (status === 'EXECUTED') {
            return { 'bg-emerald-500': true };
        }
        if (PROCESSING_STATUS_LIST.includes(status)) {
            return { 'bg-blue-500': true };
        }
        if (status === 'SKIPPED') {
            return { 'bg-amber-500': true };
        }
        if (this.isTerminalFailureStatus(status)) {
            return { 'bg-rose-500': true };
        }
        return { 'bg-slate-600': true };
    }

    public resolveOrderVisualStatus(order: DcaOrderPayload): string {
        if (order.suspension_reason) {
            return 'SUSPENDED';
        }
        return order.order_status;
    }

    public resolveTransactionHashTitle(transactionHash: string): string {
        return normalizeEvmTransactionHash(transactionHash);
    }

    private calculateSyntheticStatus(orders: DcaOrderPayload[]): string {
        if (orders.some((order) => order.suspension_reason)) {
            return 'SUSPENDED';
        }
        if (orders.some((order) => PROCESSING_STATUS_LIST.includes(order.order_status))) {
            return 'PROCESSING';
        }
        if (orders.some((order) => order.order_status === 'REJECTED' || order.order_status === 'FAILED')) {
            return 'REJECTED';
        }
        if (orders.some((order) => order.order_status === 'SKIPPED')) {
            return 'SKIPPED';
        }
        if (orders.some((order) => order.order_status === 'EXECUTED')) {
            return 'EXECUTED';
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
        const executedOrders = node.orders.filter((order) => order.order_status === 'EXECUTED' && (order.executed_source_asset_amount ?? 0) > 0);
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

    private generateCalendarRulerNodes(
        startTimestamp: number,
        endTimestamp: number,
        totalDuration: number,
        strategyEndAnchorTimestamp: number
    ): TimelineNode[] {
        const rulerNodes: TimelineNode[] = [];
        const startDate = new Date(startTimestamp);
        const endAnchorDate = new Date(strategyEndAnchorTimestamp);

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

        if (strategyEndAnchorTimestamp > startTimestamp && !rulerNodes.some((node) => node.identifier === 'strategy-end')) {
            rulerNodes.push(
                this.createTimelineNode({
                    identifier: 'strategy-end',
                    timestamp: strategyEndAnchorTimestamp,
                    leftPositionPercent: ((strategyEndAnchorTimestamp - startTimestamp) / totalDuration) * 100,
                    isMajor: false,
                    isMinor: true,
                    isMonthBoundary: false,
                    label: endAnchorDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                })
            );
        }

        const sortedNodes = [...rulerNodes].sort((nodeA, nodeB) => nodeA.timestamp - nodeB.timestamp);
        const finalNodes: TimelineNode[] = [];

        for (let nodeIndex = 0; nodeIndex < sortedNodes.length - 1; nodeIndex++) {
            const current = sortedNodes[nodeIndex];
            const next = sortedNodes[nodeIndex + 1];
            finalNodes.push(current);

            const durationSegment = next.timestamp - current.timestamp;
            if (durationSegment > 10 * 24 * 60 * 60 * 1000) {
                const currentMonth = new Date(current.timestamp).getMonth();
                const nextMonth = new Date(next.timestamp).getMonth();
                const isSameMonth = currentMonth === nextMonth;

                const startWeek = Math.min(4, Math.floor(new Date(current.timestamp).getDate() / 7) + 1);
                const endWeek = isSameMonth ? Math.min(4, Math.floor(new Date(next.timestamp).getDate() / 7) + 1) : 5;

                const missingWeeks: number[] = [];
                for (let weekNumber = startWeek + 1; weekNumber < endWeek; weekNumber++) {
                    missingWeeks.push(weekNumber);
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

        finalNodes.sort((nodeA, nodeB) => nodeA.timestamp - nodeB.timestamp);
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
