import {CommonModule} from '@angular/common';
import {Component, computed, OnInit} from '@angular/core';
import {WebSocketService} from '../core/websocket.service';

@Component({
    standalone: true,
    selector: 'app-connection-overlay-pill',
    imports: [CommonModule],
    templateUrl: './connection-overlay-pill.component.html',
    styleUrl: './connection-overlay-pill.component.css'
})
export class ConnectionOverlayPillComponent implements OnInit {

    public readonly label = computed(() => {
        const raw = this.webSocketService.status();
        return raw.toUpperCase();
    });

    constructor(private readonly webSocketService: WebSocketService) {}

    ngOnInit(): void {
        console.info('poseidon.ui.connection-overlay-pill — mounted; initial status:', this.webSocketService.status());
    }

    public isConnecting(): boolean { return this.webSocketService.status() === 'connecting'; }

    public isOpen(): boolean { return this.webSocketService.status() === 'open'; }

    public isClosed(): boolean { return this.webSocketService.status() === 'closed'; }
}
