import {DecimalPipe} from '@angular/common';
import {Component, Input} from '@angular/core';

@Component({
    standalone: true,
    selector: 'pnl-badge',
    imports: [DecimalPipe],
    templateUrl: 'pnl-badge.component.html'
})
export class PnlBadgeComponent {
    @Input() value = 0;
}
