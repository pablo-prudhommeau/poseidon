import {Component} from '@angular/core';
import {RouterOutlet} from '@angular/router';
import {NavigationComponent} from './components/navigation.component';

@Component({
    standalone: true,
    selector: 'app-root',
    imports: [RouterOutlet, NavigationComponent],
    template: `
		<app-nav></app-nav>
		<div class="mx-auto px-6 py-6">
			<router-outlet></router-outlet>
		</div>
    `
})
export class AppComponent {}
