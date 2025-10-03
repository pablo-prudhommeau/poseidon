import {CommonModule} from '@angular/common';
import {Component} from '@angular/core';
import {RouterModule} from '@angular/router';

type IconName = 'home' | 'wrench';

interface NavItem {
    label: string;
    route: string;
    icon: IconName;
    exact: boolean;
}

@Component({
    standalone: true,
    selector: 'app-nav',
    imports: [CommonModule, RouterModule],
    templateUrl: './navigation.component.html'
})
export class NavigationComponent {
    public readonly items: ReadonlyArray<NavItem> = [
        {label: 'Home', route: '/', icon: 'home', exact: true}
    ];

    constructor() {
        console.info('poseidon.ui.navbar — initialized (items:', this.items.length, ')');
    }

    public getAriaLabel(item: NavItem): string {
        return `Navigate to ${item.label}`;
    }
}
