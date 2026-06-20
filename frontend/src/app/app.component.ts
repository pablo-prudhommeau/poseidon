import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { NavigationComponent } from './components/navigation.component';

@Component({
    standalone: true,
    selector: 'app-root',
    imports: [RouterOutlet, NavigationComponent],
    template: `
		<app-nav></app-nav>
		<div class="poseidon-app-body mx-auto px-3 pb-4 pt-0 md:px-6 md:pb-6 md:pt-0">
			<router-outlet></router-outlet>
		</div>
    `
})
export class AppComponent {}
