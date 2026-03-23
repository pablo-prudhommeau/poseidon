import {Component, computed, inject, OnInit, Signal} from '@angular/core';
import {CardModule} from 'primeng/card';
import {ApiService} from '../../api.service';
import {WebSocketService} from '../../core/websocket.service';
import {DcaStrategy} from '../../core/models';
import {DcaStrategyPathProjectionComponent} from "./dca-strategy-path-projection/dca-strategy-path-projection.component";
import {DcaStrategyExecutionTimelineComponent} from "./dca-strategy-execution-timeline/dca-strategy-execution-timeline.component";
import {DcaSynthesisComponent} from "./dca-synthesis/dca-synthesis.component";
import {DcaStrategyChartsComponent} from "./dca-strategy-charts/dca-strategy-charts.component";

@Component({
    standalone: true,
    selector: 'app-dca-dashboard',
    imports: [
        CardModule,
        DcaSynthesisComponent,
        DcaStrategyPathProjectionComponent,
        DcaStrategyChartsComponent,
        DcaStrategyExecutionTimelineComponent
    ],
    templateUrl: './dca-dashboard.component.html'
})
export class DcaDashboardComponent implements OnInit {
    private readonly websocketService = inject(WebSocketService);
    private readonly apiService = inject(ApiService);

    dcaStrategies: Signal<DcaStrategy[]> = computed(() => this.websocketService.dcaStrategies());

    public readonly activeStrategy = computed<DcaStrategy>(() => {
        return this.dcaStrategies()[0];
    });

    public ngOnInit(): void {
        this.apiService.getDcaStrategies().subscribe({
            next: (strategies: DcaStrategy[]) => {
                if (this.websocketService.dcaStrategies().length === 0) {
                    this.websocketService.dcaStrategies.set(strategies);
                }
            }
        });
    }
}