import { ENVIRONMENT_INITIALIZER, Provider } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import type { ColDef, ColGroupDef, ColumnState, GridApi, GridOptions, ManagedGridOptionKey } from 'ag-grid-community';

class PoseidonAgGridHmrRegistry {
    private static readonly singleton = new PoseidonAgGridHmrRegistry();
    private readonly grids = new Set<AgGridAngular>();

    private constructor() {}

    public rebindAll(): void {
        const versionToken: number = Date.now();

        for (const grid of this.grids) {
            const api: GridApi | undefined = grid.api;
            if (!api) {
                console.debug('[UI][AGGRID][HMR][SKIP] grid.api not ready');
                continue;
            }

            const currentDefs = api.getColumnDefs() as (ColDef | ColGroupDef)[] | undefined;
            if (!currentDefs || currentDefs.length === 0) {
                console.debug('[UI][AGGRID][HMR][SKIP] no column definitions');
                continue;
            }

            const columnStateBefore: ColumnState[] = api.getColumnState();

            const nextDefs: (ColDef | ColGroupDef)[] = currentDefs.map((def) => {
                if (isColGroupDef(def)) {
                    return def;
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

            type ColumnDefsOption = NonNullable<GridOptions['columnDefs']>;
            const key: ManagedGridOptionKey = 'columnDefs';
            api.setGridOption(key, nextDefs as ColumnDefsOption);

            if (columnStateBefore.length > 0) {
                api.applyColumnState({ state: columnStateBefore, applyOrder: true });
            }

            api.refreshCells({ force: true });
        }

        console.info(`[UI][AGGRID][HMR][DONE] all grids rebound version=${versionToken}`);
    }

    public register(grid: AgGridAngular): void {
        this.grids.add(grid);
        console.info('[UI][AGGRID][HMR][REGISTER] grid registered');
    }

    public unregister(grid: AgGridAngular): void {
        this.grids.delete(grid);
        console.info('[UI][AGGRID][HMR][UNREGISTER] grid unregistered');
    }

    public static instance(): PoseidonAgGridHmrRegistry {
        return PoseidonAgGridHmrRegistry.singleton;
    }
}

function isColGroupDef(def: ColDef | ColGroupDef): def is ColGroupDef {
    return typeof (def as ColGroupDef).children !== 'undefined';
}

interface AgGridAngularLifecycle {
    ngAfterViewInit?: () => void;
    ngOnDestroy?: () => void;
}

function installAgGridHmrPatch(): void {
    const registry = PoseidonAgGridHmrRegistry.instance();

    type AgGridAngularCtor = { prototype: AgGridAngular & AgGridAngularLifecycle };
    const ctor: AgGridAngularCtor = AgGridAngular as unknown as AgGridAngularCtor;
    const proto = ctor.prototype;

    const originalAfterViewInit = proto.ngAfterViewInit;
    proto.ngAfterViewInit = function patchedAfterViewInit(this: AgGridAngular & AgGridAngularLifecycle): void {
        registry.register(this);
        if (originalAfterViewInit) {
            originalAfterViewInit.apply(this);
        }
    };

    const originalOnDestroy = proto.ngOnDestroy;
    proto.ngOnDestroy = function patchedOnDestroy(this: AgGridAngular & AgGridAngularLifecycle): void {
        registry.unregister(this);
        if (originalOnDestroy) {
            originalOnDestroy.apply(this);
        }
    };

    const metaHot = (import.meta as unknown as { hot?: { accept: (cb?: () => void) => void } }).hot;
    if (metaHot && typeof metaHot.accept === 'function') {
        metaHot.accept((): void => registry.rebindAll());
        console.info('[UI][AGGRID][HMR] accept hook installed (Vite)');
    } else {
        console.info('[UI][AGGRID][HMR] HMR not detected; patch idle');
    }
}

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
