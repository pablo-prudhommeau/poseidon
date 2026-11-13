import { Injectable } from '@angular/core';
import type { SciChartModule } from '../data/trading-shadowing-verdict-chronicle.models';

function unwrapSciChartModule(imported: unknown): SciChartModule {
    const ns = imported as SciChartModule & { default?: SciChartModule };
    if (typeof ns.SciChartSurface?.UseCommunityLicense === 'function') {
        return ns;
    }
    const fromDefault = ns.default;
    if (fromDefault && typeof fromDefault.SciChartSurface?.UseCommunityLicense === 'function') {
        return fromDefault;
    }
    throw new Error('SciChart: dynamic import did not expose SciChartSurface (CommonJS / production interop).');
}

@Injectable({
    providedIn: 'root'
})
export class TradingShadowingVerdictChronicleSciChartLoaderService {
    private static runtimeConfigured: boolean = false;

    private moduleImport: Promise<SciChartModule> | null = null;

    loadModule(): Promise<SciChartModule> {
        if (!this.moduleImport) {
            this.moduleImport = import('scichart').then((raw) => {
                const sci = unwrapSciChartModule(raw);
                if (!TradingShadowingVerdictChronicleSciChartLoaderService.runtimeConfigured) {
                    sci.SciChartSurface.UseCommunityLicense();
                    const wasmVersion = sci.libraryVersion;
                    sci.SciChartSurface.configure({
                        wasmUrl: `/scichart-wasm/scichart2d.wasm?v=${wasmVersion}`,
                        wasmNoSimdUrl: `/scichart-wasm/scichart2d-nosimd.wasm?v=${wasmVersion}`
                    });
                    TradingShadowingVerdictChronicleSciChartLoaderService.runtimeConfigured = true;
                }
                return sci;
            });
        }
        return this.moduleImport;
    }
}
