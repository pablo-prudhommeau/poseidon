import {Routes} from '@angular/router';
import {DashboardComponent} from './pages/dashboard.component';
import {ToolsComponent} from './pages/tools.component';

export const routes: Routes = [
    {path: '', component: DashboardComponent},
    {path: 'tools', component: ToolsComponent},
    {path: 'dashboard', redirectTo: '', pathMatch: 'full'},
    {path: '**', redirectTo: ''}
];
