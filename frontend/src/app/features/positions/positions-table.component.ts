import { Component } from '@angular/core';
import {NgFor, NgIf, DecimalPipe, NgClass} from '@angular/common';
import { WsService } from '../../core/ws.service';

@Component({
    standalone: true,
    selector: 'positions-table',
    imports: [NgFor, NgIf, DecimalPipe, NgClass],
    templateUrl: './positions-table.component.html'
})
export class PositionsTableComponent {
    constructor(public ws: WsService) {}
}
