import {CommonModule} from '@angular/common';
import {Component, inject, OnInit} from '@angular/core';
import {RouterModule} from '@angular/router';
import {WebSocketService} from '../core/websocket.service';
import {ConnectionOverlayPillComponent} from '../widgets/connection-overlay-pill.component';
import {PaperModeControlComponent} from '../widgets/paper-mode-control.component';

interface NavigationItem {
    label: string;
    route: string;
    icon: string;
    exact: boolean;
}

@Component({
    standalone: true,
    selector: 'app-nav',
    imports: [CommonModule, RouterModule, ConnectionOverlayPillComponent, PaperModeControlComponent],
    templateUrl: './navigation.component.html'
})
export class NavigationComponent implements OnInit {

    private webSocketService = inject(WebSocketService);

    public readonly items: ReadonlyArray<NavigationItem> = [
        {label: 'Home', route: '/', icon: 'home', exact: true},
        {label: 'Analytics', route: '/analytics', icon: 'chart-area', exact: false}
    ];

    ngOnInit(): void {
        this.webSocketService.connect();
    }

    public trackByRoute(_: number, item: NavigationItem): string {
        return item.route;
    }

    public getAriaLabel(item: NavigationItem): string {
        return `Navigate to ${item.label}`;
    }
}
