import {JsonPipe} from '@angular/common';
import {AfterViewInit, Component, computed, inject, signal, TemplateRef, ViewChild} from '@angular/core';
import {AgGridAngular} from 'ag-grid-angular';
import {CellClassParams, ColDef, ValueFormatterParams, ValueGetterParams} from 'ag-grid-community';
import {ButtonModule} from 'primeng/button';
import {DialogModule} from 'primeng/dialog';
import {balhamDarkThemeCompact} from '../../ag-grid.theme';
import {DefiIconsService} from '../../core/defi-icons.service';
import {NumberFormattingService} from '../../core/number-formatting.service';
import {WebSocketService} from '../../core/websocket.service';
import {SymbolChipRendererComponent} from '../../renderers/symbol-chip.renderer';
import {TemplateCellRendererComponent} from '../../renderers/template-cell.renderer';
import {TemplateHeaderRendererComponent} from '../../renderers/template-header.renderer';

@Component({
    standalone: true,
    selector: 'positions-table',
    imports: [AgGridAngular, DialogModule, ButtonModule, JsonPipe],
    templateUrl: './positions-table.component.html'
})
export class PositionsTableComponent implements AfterViewInit {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly webSocketService = inject(WebSocketService);
    private readonly defiIconsService = inject(DefiIconsService);
    private readonly numberFormattingService = inject(NumberFormattingService);

    public readonly positionsRowData = computed<any[]>(() => {
        const rows = this.webSocketService.positions() ?? [];
        return Array.isArray(rows) ? [...rows] : [];
    });

    public columnDefinitions: ColDef[] = [];
    public readonly defaultColumnDefinition: ColDef = {
        resizable: true,
        sortable: true,
        filter: true,
        suppressHeaderMenuButton: false,
        flex: 1
    };

    @ViewChild('actionsTemplate', {static: false}) private actionsTemplate?: TemplateRef<unknown>;
    @ViewChild('symbolHeaderTemplate', {static: false}) private symbolHeaderTemplate?: TemplateRef<unknown>;

    public readonly detailsVisible = signal<boolean>(false);
    public readonly selectedRow = signal<any | null>(null);

    public ngAfterViewInit(): void {
        this.columnDefinitions = [
            {
                headerName: 'Symbol',
                field: 'symbol',
                sortable: true,
                filter: true,
                cellRenderer: SymbolChipRendererComponent,
                comparator: (a, b) => String(a ?? '').localeCompare(String(b ?? ''), undefined, {sensitivity: 'base'}),
                flex: 1.6,
                headerComponent: this.symbolHeaderTemplate ? TemplateHeaderRendererComponent : undefined,
                headerComponentParams: this.symbolHeaderTemplate ? {template: this.symbolHeaderTemplate} : undefined
            },
            {
                headerName: 'Open date',
                field: 'open_date',
                sortable: true,
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams) => p.data?.opened_at ?? null,
                cellClass: 'whitespace-nowrap',
                flex: 1.4
            },
            {
                headerName: 'Quantity',
                field: 'qty',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatNumber(p.value, 2, 4),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.3
            },
            {
                headerName: 'Entry',
                field: 'entry',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'TP1',
                field: 'tp1',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'TP2',
                field: 'tp2',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'Stop',
                field: 'stop',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'Δ %',
                colId: 'deltaPercent',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams) => {
                    const enriched = this.numberFormattingService.toNumberSafe(p.data?._changePct);
                    if (enriched !== null) {
                        return enriched;
                    }
                    const last = this.numberFormattingService.toNumberSafe(p.data?.last_price);
                    const entry = this.numberFormattingService.toNumberSafe(p.data?.entry);
                    if (last === null || entry === null || entry === 0) {
                        return null;
                    }
                    return ((last - entry) / Math.abs(entry)) * 100;
                },
                valueFormatter: (p: ValueFormatterParams) =>
                    p.value == null ? '—' : `${this.numberFormattingService.formatNumber(p.value, 2, 2)}%`,
                cellClassRules: {'pct-up': (p) => (p.value ?? 0) > 0, 'pct-down': (p) => (p.value ?? 0) < 0},
                cellClass: 'text-right whitespace-nowrap',
                flex: 0.9
            },
            {
                headerName: 'Phase',
                field: 'phase',
                sortable: true,
                cellRenderer: (p: ValueFormatterParams) => {
                    let colorClass = '';
                    if (p.value === 'OPEN') {
                        colorClass = 'bg-blue-600';
                    } else if (p.value === 'PARTIAL') {
                        colorClass = 'bg-yellow-600';
                    } else if(p.value === 'STALED'){
                        colorClass = 'bg-gray-600';
                    }
                    return `<span class="${colorClass} saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">${p.value}</span>`;
                }
            },
            {
                headerName: 'Last price',
                field: 'last_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams) => this.numberFormattingService.toNumberSafe(p.data?.last_price),
                valueFormatter: (p: ValueFormatterParams) =>
                    p.value == null ? '—' : this.numberFormattingService.formatNumber(p.value, 4, 8),
                cellClass: (p: CellClassParams) => {
                    const direction = (p.data as any)?._lastDir;
                    if (direction === 'up') {
                        return 'text-right whitespace-nowrap price-up';
                    }
                    if (direction === 'down') {
                        return 'text-right whitespace-nowrap price-down';
                    }
                    return 'text-right whitespace-nowrap';
                },
                flex: 1.2
            },
            {
                headerName: 'Actions',
                colId: 'actions',
                pinned: 'right',
                width: 80,
                suppressHeaderMenuButton: true,
                sortable: false,
                filter: false,
                cellRenderer: TemplateCellRendererComponent,
                cellRendererParams: {template: this.actionsTemplate},
            },
        ];
    }

    public openDetails(row: unknown): void {
        this.selectedRow.set(row ?? null);
        this.detailsVisible.set(true);
        console.info('[UI][POSITIONS][DETAILS] open', row);
    }
}
