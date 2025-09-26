import { Component } from '@angular/core';
import { NgFor, NgIf, DecimalPipe, NgClass } from '@angular/common';
import { WsService } from '../../core/ws.service';
import { TokenChipComponent } from '../../widgets/token-chip.component';

@Component({
    standalone: true,
    selector: 'positions-table',
    imports: [NgFor, NgIf, DecimalPipe, NgClass, TokenChipComponent],
    templateUrl: './positions-table.component.html'
})
export class PositionsTableComponent {
    constructor(public ws: WsService) {}
}
