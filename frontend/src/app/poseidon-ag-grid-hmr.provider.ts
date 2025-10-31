import { ENVIRONMENT_INITIALIZER, Provider } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import type {
    ColDef,
    ColGroupDef,
    ColumnState,
    GridApi,
    GridOptions,
    ManagedGridOptionKey
} from 'ag-grid-community';

/**
 * [UI][AGGRID][HMR] PoseidonAgGridHmrRegistry (AG Grid v34 only)
 *
 * Registers all AgGridAngular instances and, on every HMR accept, forces
 * renderer re-creation by reapplying fresh columnDefs while preserving
 * column state (order, width, pinned, visibility).
 *
 * Logging format: [UI][AGGRID][HMR][...]
 */
class PoseidonAgGridHmrRegistry {
    private static readonly singleton = new PoseidonAgGridHmrRegistry();
    private readonly grids = new Set<AgGridAngular>();

    private constructor() {}

    public static instance(): PoseidonAgGridHmrRegistry {
        return PoseidonAgGridHmrRegistry.singleton;
    }

    public register(grid: AgGridAngular): void {
        this.grids.add(grid);
        console.info('[UI][AGGRID][HMR][REGISTER] grid registered');
    }

    public unregister(grid: AgGridAngular): void {
        this.grids.delete(grid);
        console.info('[UI][AGGRID][HMR][UNREGISTER] grid unregistered');
    }

    /**
     * Forces renderer re-creation on all registered grids by:
     * 1) reading current columnDefs,
     * 2) cloning each definition and bumping params identity,
     * 3) re-applying columnDefs via setGridOption('columnDefs', ...),
     * 4) restoring column state,
     * 5) refreshing cells.
     */
    public rebindAll(): void {
        const versionToken: number = Date.now();

        for (const grid of this.grids) {
            const api: GridApi | undefined = grid.api;
            if (!api) {
                console.debug('[UI][AGGRID][HMR][SKIP] grid.api not ready');
                continue;
            }

            // 1) Read current defs (AG Grid v34).
            const currentDefs = api.getColumnDefs() as (ColDef | ColGroupDef)[] | undefined;
            if (!currentDefs || currentDefs.length === 0) {
                console.debug('[UI][AGGRID][HMR][SKIP] no column definitions');
                continue;
            }

            // Capture state before rebind.
            const columnStateBefore: ColumnState[] = api.getColumnState();

            // 2) Clone defs and bump params identity only on leaf columns.
            const nextDefs: (ColDef | ColGroupDef)[] = currentDefs.map((def) => {
                if (isColGroupDef(def)) {
                    return def; // keep groups intact
                }

                const leaf = def as ColDef;
                const hasCellParams = typeof leaf.cellRendererParams === 'object' && leaf.cellRendererParams !== null;
                const hasHeaderParams = typeof leaf.headerComponentParams === 'object' && leaf.headerComponentParams !== null;

                const nextCellParams = hasCellParams
                    ? { ...(leaf.cellRendererParams as Record<string, unknown>), __poseidonHmrVersion: versionToken }
                    : undefined;

                const nextHeaderParams = hasHeaderParams
                    ? { ...(leaf.headerComponentParams as Record<string, unknown>), __poseidonHmrVersion: versionToken }
                    : undefined;

                const nextLeaf: ColDef = {
                    ...leaf,
                    ...(nextCellParams ? { cellRendererParams: nextCellParams } : {}),
                    ...(nextHeaderParams ? { headerComponentParams: nextHeaderParams } : {})
                };

                return nextLeaf;
            });

            console.info('[UI][AGGRID][HMR][REBUILD] applying next column definitions');

            // 3) Re-apply defs (typed key/value for v34).
            type ColumnDefsOption = NonNullable<GridOptions['columnDefs']>;
            const key: ManagedGridOptionKey = 'columnDefs';
            api.setGridOption(key, nextDefs as ColumnDefsOption);

            // 4) Restore state.
            if (columnStateBefore.length > 0) {
                api.applyColumnState({ state: columnStateBefore, applyOrder: true });
            }

            // 5) Hard refresh for safety.
            api.refreshCells({ force: true });
        }

        console.info(`[UI][AGGRID][HMR][DONE] all grids rebound version=${versionToken}`);
    }
}

/** Type guard: detect a ColGroupDef. */
function isColGroupDef(def: ColDef | ColGroupDef): def is ColGroupDef {
    return typeof (def as ColGroupDef).children !== 'undefined';
}

/** Lifecycle hooks we patch on AgGridAngular prototype (typed, no any). */
interface AgGridAngularLifecycle {
    ngAfterViewInit?: () => void;
    ngOnDestroy?: () => void;
}

/**
 * Install a single global patch:
 * - auto-register/unregister every grid instance,
 * - Vite HMR accept hook that triggers rebindAll().
 */
function installAgGridHmrPatch(): void {
    const registry = PoseidonAgGridHmrRegistry.instance();

    type AgGridAngularCtor = { prototype: AgGridAngular & AgGridAngularLifecycle };
    const ctor: AgGridAngularCtor = AgGridAngular as unknown as AgGridAngularCtor;
    const proto = ctor.prototype;

    const originalAfterViewInit = proto.ngAfterViewInit;
    proto.ngAfterViewInit = function patchedAfterViewInit(this: AgGridAngular & AgGridAngularLifecycle): void {
        registry.register(this);
        if (originalAfterViewInit) originalAfterViewInit.apply(this);
    };

    const originalOnDestroy = proto.ngOnDestroy;
    proto.ngOnDestroy = function patchedOnDestroy(this: AgGridAngular & AgGridAngularLifecycle): void {
        registry.unregister(this);
        if (originalOnDestroy) originalOnDestroy.apply(this);
    };

    // Angular ≥17 uses Vite HMR.
    const metaHot = (import.meta as unknown as { hot?: { accept: (cb?: () => void) => void } }).hot;
    if (metaHot && typeof metaHot.accept === 'function') {
        metaHot.accept((): void => registry.rebindAll());
        console.info('[UI][AGGRID][HMR] accept hook installed (Vite)');
    } else {
        console.info('[UI][AGGRID][HMR] HMR not detected; patch idle');
    }
}

/** Public provider: add once in app.config.ts */
export function providePoseidonAgGridHmr(): Provider {
    return {
        provide: ENVIRONMENT_INITIALIZER,
        multi: true,
        useValue: (): void => {
            console.info('[UI][AGGRID][HMR] installing global patch (v34)');
            installAgGridHmrPatch();
        }
    };
}
