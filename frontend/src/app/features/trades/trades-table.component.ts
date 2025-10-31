import {JsonPipe} from '@angular/common';
import {AfterViewInit, Component, computed, inject, signal, TemplateRef, ViewChild} from '@angular/core';
import {AgGridAngular} from 'ag-grid-angular';
import {ColDef, ValueFormatterParams, ValueGetterParams} from 'ag-grid-community';
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
    selector: 'trades-table',
    imports: [AgGridAngular, DialogModule, ButtonModule, JsonPipe],
    templateUrl: './trades-table.component.html'
})
export class TradesTableComponent implements AfterViewInit {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly webSocketService = inject(WebSocketService);
    private readonly numberFormattingService = inject(NumberFormattingService);
    private readonly defiIconsService = inject(DefiIconsService);

    public readonly tradesRowData = computed<any[]>(() => {
        const rows = this.webSocketService.trades() ?? [];
        return Array.isArray(rows) ? [...rows] : [];
    });

    public columnDefinitions: ColDef[] = [];
    public readonly defaultColumnDefinition: ColDef = {resizable: true, sortable: true, filter: true, flex: 1};

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
                flex: 1.2,
                headerComponent: this.symbolHeaderTemplate ? TemplateHeaderRendererComponent : undefined,
                headerComponentParams: this.symbolHeaderTemplate ? {template: this.symbolHeaderTemplate} : undefined
            },
            {
                headerName: 'Date',
                field: 'created_at',
                sortable: true,
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams) => p.data?.created_at ?? p.data?.date ?? null,
                flex: 1
            },
            {
                headerName: 'Side',
                field: 'side',
                sortable: true,
                filter: true,
                cellRenderer: (p: ValueFormatterParams) => {
                    let colorClass = '';
                    if (p.value === 'BUY') {
                        colorClass = 'bg-teal-600';
                    } else if (p.value === 'SELL') {
                        colorClass = 'bg-indigo-500';
                    }
                    return `<span class="${colorClass} saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">${p.value}</span>`;
                },
                flex: 0.5
            },
            {
                headerName: 'Quantity',
                field: 'qty',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatNumber(p.value, 2, 6),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.3
            },
            {
                headerName: 'Price',
                field: 'price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'P&L',
                field: 'pnl',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 2, 2),
                cellClass: (p: ValueFormatterParams) => {
                    const n = this.numberFormattingService.toNumberSafe(p.value);
                    if (n === null) {
                        return 'text-right whitespace-nowrap';
                    }
                    return n > 0 ? 'text-right whitespace-nowrap text-green-400'
                        : n < 0 ? 'text-right whitespace-nowrap text-red-400'
                            : 'text-right whitespace-nowrap';
                },
                flex: 1
            },
            {
                headerName: 'Status',
                field: 'status',
                sortable: true,
                filter: true,
                flex: 0.5
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
                cellRendererParams: {template: this.actionsTemplate}
            }
        ];
    }

    public openDetails(row: unknown): void {
        this.selectedRow.set(row ?? null);
        this.detailsVisible.set(true);
        console.info('[UI][TRADES][DETAILS] open', row);
    }
}
