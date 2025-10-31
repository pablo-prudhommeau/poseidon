import {provideHttpClient, withFetch} from '@angular/common/http';
import {ApplicationConfig, provideBrowserGlobalErrorListeners, provideZoneChangeDetection} from '@angular/core';
import {provideAnimationsAsync} from '@angular/platform-browser/animations/async';
import {provideRouter} from '@angular/router';
import {providePrimeNG} from 'primeng/config';
import {routes} from './app.routes';
import {providePoseidonAgGridHmr} from './poseidon-ag-grid-hmr.provider';
import PoseidonPreset from './poseidon.preset';

export const appConfig: ApplicationConfig = {

    providers: [
        provideBrowserGlobalErrorListeners(),
        provideZoneChangeDetection({eventCoalescing: true}),
        provideRouter(routes),
        provideHttpClient(withFetch()),
        provideAnimationsAsync(),
        providePrimeNG({
            theme: {
                preset: PoseidonPreset
            }
        }),
        providePoseidonAgGridHmr()
    ]
};
