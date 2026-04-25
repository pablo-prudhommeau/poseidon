import {CommonModule} from '@angular/common';
import {Component, inject, OnInit} from '@angular/core';
import {RouterModule} from '@angular/router';
import {WebSocketService} from '../core/websocket.service';
import {ConnectionOverlayPillComponent} from '../widgets/connection-overlay-pill/connection-overlay-pill.component';
import {PaperModeControlComponent} from '../widgets/paper-mode-control/paper-mode-control.component';

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
        {label: 'Trading', route: '/trading', icon: 'chart-line', exact: false},
        {label: 'Smart DCA', route: '/dca', icon: 'robot', exact: false}
    ];

    ngOnInit(): void {
        this.webSocketService.connect();
    }

    public getAriaLabel(item: NavigationItem): string {
        return `Maps to ${item.label}`;
    }
}