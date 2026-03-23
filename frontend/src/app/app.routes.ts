import {Routes} from '@angular/router';
import {DashboardComponent} from './pages/dashboard/dashboard.component';
import {AnalyticsComponent} from './pages/analytics/analytics.component';
import {DcaDashboardComponent} from './pages/dca/dca-dashboard.component';

/**
 * Application routes
 * - Keeps existing dashboard as root
 * - Adds Analytics pages
 * - Adds Smart DCA Dashboard
 */
export const routes: Routes = [
    {path: '', component: DashboardComponent},
    {path: 'dashboard', redirectTo: '', pathMatch: 'full'},
    {path: 'analytics', component: AnalyticsComponent},
    {path: 'dca', component: DcaDashboardComponent},
    {path: '**', redirectTo: ''},
];