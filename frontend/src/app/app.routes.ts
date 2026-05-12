import { Routes } from '@angular/router';
import { DcaDashboardComponent } from './pages/dca/dca-dashboard.component';
import { TradingDashboardComponent } from './pages/trading/trading-dashboard.component';

export const routes: Routes = [
    { path: 'trading', component: TradingDashboardComponent },
    { path: 'dca', component: DcaDashboardComponent },
    { path: 'analytics', redirectTo: 'trading', pathMatch: 'full' },
    { path: 'dashboard', redirectTo: 'trading', pathMatch: 'full' },
    { path: '', redirectTo: 'trading', pathMatch: 'full' },
    { path: '**', redirectTo: 'trading' }
];
