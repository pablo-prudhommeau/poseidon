import {JsonPipe} from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { ColDef, ValueFormatterParams, ValueGetterParams } from 'ag-grid-community';
import { DialogModule } from 'primeng/dialog';
import { ButtonModule } from 'primeng/button';
import { balhamDarkThemeCompact } from '../../ag-grid.theme';
import { DateFormattingService } from '../../core/date-formatting.service';
import { DefiIconsService } from '../../core/defi-icons.service';
import { NumberFormattingService } from '../../core/number-formatting.service';
import { WebSocketService } from '../../core/websocket.service';

/**
 * TradesTableComponent
 * --------------------
 * Displays recent trades with a pinned 'Actions' column that opens a details modal.
 * The Symbol column uses DefiIconsService to render a triple icon (chain+token+pair).
 */
@Component({
    standalone: true,
    selector: 'trades-table',
    imports: [AgGridAngular, DialogModule, ButtonModule, JsonPipe],
    templateUrl: './trades-table.component.html',
})
export class TradesTableComponent {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly webSocketService = inject(WebSocketService);
    private readonly numberFormattingService = inject(NumberFormattingService);
    private readonly dateFormattingService = inject(DateFormattingService);
    private readonly defiIconService = inject(DefiIconsService);

    public readonly tradesRowData = computed<any[]>(() => {
        const rows = this.webSocketService.trades() ?? [];
        return Array.isArray(rows) ? [...rows] : [];
    });

    // Modal state
    public readonly detailsVisible = signal<boolean>(false);
    public readonly selectedRow = signal<any | null>(null);

    public openDetails(row: any): void {
        this.selectedRow.set(row);
        this.detailsVisible.set(true);
        console.info('[UI][TRADES][DETAILS] open', {
            symbol: row?.symbol,
            chain: row?.chain,
            tokenAddress: row?.tokenAddress ?? row?.address,
            pairAddress: row?.pairAddress,
            side: row?.side,
        });
    }

    public readonly columnDefinitions: ColDef[] = [
        {
            headerName: 'Symbol',
            field: 'symbol',
            sortable: true,
            filter: true,
            cellRenderer: this.defiIconService.tokenChainPairChipRenderer,
            flex: 1.2,
        },
        {
            headerName: 'Date',
            field: 'created_at',
            sortable: true,
            filter: 'agDateColumnFilter',
            valueGetter: (p: ValueGetterParams) => p.data?.created_at ?? p.data?.date ?? null,
            flex: 1,
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
                return (
                    '<span class="' +
                    colorClass +
                    ' saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">' +
                    p.value +
                    '</span>'
                );
            },
            flex: 0.5,
        },
        {
            headerName: 'Quantity',
            field: 'qty',
            type: 'numericColumn',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatNumber(p.value, 2, 6),
            cellClass: 'text-right whitespace-nowrap',
            flex: 1.3,
        },
        {
            headerName: 'Price',
            field: 'price',
            type: 'numericColumn',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
            cellClass: 'text-right whitespace-nowrap',
            flex: 1.1,
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
                return n > 0
                    ? 'text-right whitespace-nowrap text-green-400'
                    : n < 0
                        ? 'text-right whitespace-nowrap text-red-400'
                        : 'text-right whitespace-nowrap';
            },
            flex: 1,
        },
        {
            headerName: 'Status',
            field: 'status',
            sortable: true,
            filter: true,
            flex: 0.5,
        },
        // -------- Actions column (pinned right) --------
        {
            headerName: '',
            colId: 'actions',
            pinned: 'right',
            width: 70,
            suppressHeaderMenuButton: true,
            sortable: false,
            filter: false,
            cellRenderer: () =>
                `<button class="p-button p-component p-button-sm p-button-rounded p-button-text" title="Details">
           <span class="pi pi-search"></span>
         </button>`,
            onCellClicked: (p) => this.openDetails(p.data),
        },
    ];

    public readonly defaultColumnDefinition: ColDef = {
        resizable: true,
        sortable: true,
        filter: true,
        flex: 1,
    };
}
