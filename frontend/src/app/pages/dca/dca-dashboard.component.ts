import { Component, computed, effect, inject, OnInit, Signal, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CardModule } from 'primeng/card';
import { SelectModule } from 'primeng/select';
import { ApiService } from '../../api.service';
import { DcaStrategyPayload } from '../../core/models';
import { WebSocketService } from '../../core/websocket.service';
import { DcaStrategyChartsComponent } from './dca-strategy-charts/dca-strategy-charts.component';
import { DcaStrategyExecutionTimelineComponent } from './dca-strategy-execution-timeline/dca-strategy-execution-timeline.component';
import { DcaStrategyPathProjectionComponent } from './dca-strategy-path-projection/dca-strategy-path-projection.component';
import { DcaSynthesisComponent } from './dca-synthesis/dca-synthesis.component';

@Component({
    standalone: true,
    selector: 'app-dca-dashboard',
    imports: [
        FormsModule,
        CardModule,
        SelectModule,
        DcaSynthesisComponent,
        DcaStrategyPathProjectionComponent,
        DcaStrategyChartsComponent,
        DcaStrategyExecutionTimelineComponent
    ],
    templateUrl: './dca-dashboard.component.html'
})
export class DcaDashboardComponent implements OnInit {
    private readonly websocketService = inject(WebSocketService);

    public readonly dcaStrategies: Signal<DcaStrategyPayload[]> = computed(() => this.websocketService.dcaStrategies());
    public readonly selectedStrategyId = signal<number | null>(null);
    public readonly activeStrategy = computed<DcaStrategyPayload | null>(() => {
        const strategiesList = this.dcaStrategies();
        if (strategiesList.length === 0) {
            return null;
        }

        const currentId = this.selectedStrategyId();
        if (currentId === null) {
            return strategiesList[0];
        }

        return strategiesList.find((strategy: DcaStrategyPayload) => strategy.id === currentId) ?? strategiesList[0];
    });

    private readonly apiService = inject(ApiService);

    constructor() {
        effect(() => {
            const strategies = this.dcaStrategies();
            if (strategies.length > 0 && this.selectedStrategyId() === null) {
                this.selectedStrategyId.set(strategies[0].id);
            }
        });
    }

    public ngOnInit(): void {
        this.apiService.getDcaStrategies().subscribe({
            next: (strategies: DcaStrategyPayload[]) => {
                if (this.websocketService.dcaStrategies().length === 0) {
                    this.websocketService.dcaStrategies.set(strategies);
                }
            }
        });
    }
}
