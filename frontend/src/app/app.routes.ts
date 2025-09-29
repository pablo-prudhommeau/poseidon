import {Routes} from '@angular/router';
import {DashboardComponent} from './pages/dashboard.component';

export const routes: Routes = [
    {path: '', component: DashboardComponent},
    {path: 'dashboard', redirectTo: '', pathMatch: 'full'},
    {path: '**', redirectTo: ''}
];
