import { Routes } from '@angular/router';
import {DashboardComponent} from './pages/dashboard/dashboard.component';
import {AnalyticsComponent} from './pages/analytics/analytics.component';

/**
 * Application routes
 * - Keeps existing dashboard as root
 * - Adds Analytics pages
 */
export const routes: Routes = [
    { path: '', component: DashboardComponent },
    { path: 'dashboard', redirectTo: '', pathMatch: 'full' },
    { path: 'analytics', component: AnalyticsComponent },
    { path: '**', redirectTo: '' },
];
