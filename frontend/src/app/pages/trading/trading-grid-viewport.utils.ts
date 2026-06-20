import { ColumnState, GridApi } from 'ag-grid-community';

type SavedColumnConstraints = {
    minWidth?: number;
    maxWidth?: number;
    width?: number;
    flex?: number | null | undefined;
    suppressSizeToFit?: boolean;
    resizable?: boolean;
};

type FlexColumnLayout = {
    flex: number;
    minWidth: number;
};

type FixedColumnLayout = {
    width: number;
};

type MobileColumnLayout = FlexColumnLayout | FixedColumnLayout;

function isFlexColumnLayout(layout: MobileColumnLayout): layout is FlexColumnLayout {
    return (layout as FlexColumnLayout).flex !== undefined;
}

export type MobileTradingGridColumnLayoutMap = Record<string, MobileColumnLayout>;

export const tradingGridCompactViewportQuery = '(max-width: 768px)';

export const tradingGridsMobileColumnLayout = {
    symbol: { flex: 0.65, minWidth: 40 } satisfies FlexColumnLayout,
    phaseOrSide: { flex: 0.65, minWidth: 40 } satisfies FlexColumnLayout,
    deltaOrProfitAndLoss: { flex: 1.2, minWidth: 64 } satisfies FlexColumnLayout,
    openPositionsActions: { width: 116 } satisfies FixedColumnLayout,
    recentTradesActions: { width: 84 } satisfies FixedColumnLayout
} as const satisfies Record<string, MobileColumnLayout>;

export interface MobileTradingGridLayoutOptions {
    columnOrder: readonly string[];
    layoutByColumnIdentifier: MobileTradingGridColumnLayoutMap;
}

const savedColumnConstraintsByGrid = new WeakMap<GridApi, Map<string, SavedColumnConstraints>>();

export function isTradingGridCompactViewport(): boolean {
    return window.matchMedia(tradingGridCompactViewportQuery).matches;
}

function rememberColumnConstraints(gridApi: GridApi, columnIdentifier: string): void {
    const column = gridApi.getColumn(columnIdentifier);
    if (column === null) {
        return;
    }
    let savedByColumn = savedColumnConstraintsByGrid.get(gridApi);
    if (savedByColumn === undefined) {
        savedByColumn = new Map<string, SavedColumnConstraints>();
        savedColumnConstraintsByGrid.set(gridApi, savedByColumn);
    }
    if (savedByColumn.has(columnIdentifier)) {
        return;
    }
    const columnDefinition = column.getColDef();
    savedByColumn.set(columnIdentifier, {
        minWidth: columnDefinition.minWidth,
        maxWidth: columnDefinition.maxWidth,
        width: columnDefinition.width,
        flex: columnDefinition.flex ?? null,
        suppressSizeToFit: columnDefinition.suppressSizeToFit,
        resizable: columnDefinition.resizable
    });
}

function restoreColumnConstraints(gridApi: GridApi): void {
    const savedByColumn = savedColumnConstraintsByGrid.get(gridApi);
    if (savedByColumn === undefined) {
        return;
    }
    for (const [columnIdentifier, saved] of savedByColumn.entries()) {
        const column = gridApi.getColumn(columnIdentifier);
        if (column === null) {
            continue;
        }
        const columnDefinition = column.getColDef();
        columnDefinition.minWidth = saved.minWidth;
        columnDefinition.maxWidth = saved.maxWidth;
        columnDefinition.width = saved.width;
        columnDefinition.flex = saved.flex ?? undefined;
        columnDefinition.suppressSizeToFit = saved.suppressSizeToFit;
        columnDefinition.resizable = saved.resizable;
    }
    savedByColumn.clear();
}

function applyColumnDefinitionConstraints(gridApi: GridApi, columnIdentifier: string, layout: MobileColumnLayout): void {
    const column = gridApi.getColumn(columnIdentifier);
    if (column === null) {
        return;
    }
    const columnDefinition = column.getColDef();
    columnDefinition.resizable = false;
    columnDefinition.suppressSizeToFit = !isFlexColumnLayout(layout);
    if (isFlexColumnLayout(layout)) {
        columnDefinition.minWidth = layout.minWidth;
        columnDefinition.maxWidth = undefined;
    } else {
        columnDefinition.minWidth = layout.width;
        columnDefinition.maxWidth = layout.width;
    }
}

function buildVisibleColumnState(columnIdentifier: string, layout: MobileColumnLayout): ColumnState {
    if (isFlexColumnLayout(layout)) {
        return {
            colId: columnIdentifier,
            hide: false,
            flex: layout.flex,
            width: undefined
        };
    }
    return {
        colId: columnIdentifier,
        hide: false,
        flex: null,
        width: layout.width
    };
}

export function applyMobileTradingGridLayout(gridApi: GridApi, options: MobileTradingGridLayoutOptions): void {
    const visibleColumnIdentifiers = new Set<string>(options.columnOrder);
    const allColumnIdentifiers: string[] = gridApi.getColumns()?.map((column) => column.getColId()) ?? [];

    if (allColumnIdentifiers.length === 0) {
        return;
    }

    for (const columnIdentifier of allColumnIdentifiers) {
        rememberColumnConstraints(gridApi, columnIdentifier);
    }

    const hiddenColumnIdentifiers = allColumnIdentifiers.filter((columnIdentifier) => !visibleColumnIdentifiers.has(columnIdentifier));

    const columnState: ColumnState[] = [];
    for (const columnIdentifier of options.columnOrder) {
        const layout = options.layoutByColumnIdentifier[columnIdentifier];
        if (layout === undefined) {
            continue;
        }
        applyColumnDefinitionConstraints(gridApi, columnIdentifier, layout);
        columnState.push(buildVisibleColumnState(columnIdentifier, layout));
    }
    for (const columnIdentifier of hiddenColumnIdentifiers) {
        columnState.push({ colId: columnIdentifier, hide: true, flex: null });
    }

    gridApi.applyColumnState({
        state: columnState,
        applyOrder: true,
        defaultState: { flex: null }
    });

    requestAnimationFrame(() => {
        if (gridApi.isDestroyed()) {
            return;
        }
        gridApi.applyColumnState({
            state: columnState,
            applyOrder: true,
            defaultState: { flex: null }
        });
    });
}

export function resetGridColumnLayout(gridApi: GridApi): void {
    restoreColumnConstraints(gridApi);
    gridApi.resetColumnState();
}
