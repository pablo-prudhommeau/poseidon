import {Component, input} from '@angular/core';
import {DatePipe, DecimalPipe, NgClass, SlicePipe} from '@angular/common';
import {CardModule} from 'primeng/card';
import {DcaStrategy} from '../../../core/models';

@Component({
    standalone: true,
    selector: 'app-dca-strategy-execution-timeline',
    imports: [DatePipe, DecimalPipe, NgClass, SlicePipe, CardModule],
    templateUrl: './dca-strategy-execution-timeline.component.html'
})
export class DcaStrategyExecutionTimelineComponent {
    public strategy = input.required<DcaStrategy>();
}