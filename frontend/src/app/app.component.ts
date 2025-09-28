import {Component} from '@angular/core';
import {RouterOutlet} from '@angular/router';
import {NavigationComponent} from './components/navigation.component';

@Component({
    standalone: true,
    selector: 'app-root',
    imports: [RouterOutlet, NavigationComponent],
    template: `
	    <app-nav></app-nav>
	    <router-outlet></router-outlet>
    `
})
export class AppComponent {}
