import { Injectable } from '@angular/core';
import type { DcaStrategyPathSciChartModule } from '../data/dca-strategy-path-projection.models';

function unwrapSciChartModule(imported: unknown): DcaStrategyPathSciChartModule {
    const namespace = imported as DcaStrategyPathSciChartModule & { default?: DcaStrategyPathSciChartModule };
    if (typeof namespace.SciChartSurface?.UseCommunityLicense === 'function') {
        return namespace;
    }
    const defaultNamespace = namespace.default;
    if (defaultNamespace && typeof defaultNamespace.SciChartSurface?.UseCommunityLicense === 'function') {
        return defaultNamespace;
    }
    throw new Error('SciChart: dynamic import did not expose SciChartSurface (CommonJS / production interop).');
}

@Injectable({
    providedIn: 'root'
})
export class DcaStrategyPathProjectionSciChartLoaderService {
    private static runtimeConfigured: boolean = false;

    private moduleImport: Promise<DcaStrategyPathSciChartModule> | null = null;

    loadModule(): Promise<DcaStrategyPathSciChartModule> {
        if (!this.moduleImport) {
            this.moduleImport = import('scichart').then((rawModule: unknown) => {
                const sciChartModule: DcaStrategyPathSciChartModule = unwrapSciChartModule(rawModule);
                if (!DcaStrategyPathProjectionSciChartLoaderService.runtimeConfigured) {
                    sciChartModule.SciChartSurface.UseCommunityLicense();
                    sciChartModule.SciChartSurface.configure({
                        wasmUrl: '/scichart-wasm/scichart2d.wasm',
                        wasmNoSimdUrl: '/scichart-wasm/scichart2d-nosimd.wasm'
                    });
                    DcaStrategyPathProjectionSciChartLoaderService.runtimeConfigured = true;
                }
                return sciChartModule;
            });
        }
        return this.moduleImport;
    }
}
