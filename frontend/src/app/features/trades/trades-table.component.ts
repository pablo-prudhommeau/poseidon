import { Component } from '@angular/core';
import { NgFor, NgIf, DecimalPipe, DatePipe } from '@angular/common';
import { WsService } from '../../core/ws.service';

@Component({
    standalone: true,
    selector: 'trades-table',
    imports: [NgFor, NgIf, DecimalPipe, DatePipe],
    templateUrl: './trades-table.component.html'
})
export class TradesTableComponent {
    constructor(public ws: WsService) {}
}
