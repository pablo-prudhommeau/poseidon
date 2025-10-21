import {JsonPipe} from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { CellClassParams, ColDef, ValueFormatterParams, ValueGetterParams } from 'ag-grid-community';
import { DialogModule } from 'primeng/dialog';
import { ButtonModule } from 'primeng/button';
import { balhamDarkThemeCompact } from '../../ag-grid.theme';
import { DefiIconsService } from '../../core/defi-icons.service';
import { NumberFormattingService } from '../../core/number-formatting.service';
import { WebSocketService } from '../../core/websocket.service';

/**
 * PositionsTableComponent
 * -----------------------
 * Displays open positions with a pinned 'Actions' column that opens a details modal.
 * The Symbol column uses DefiIconsService to render a compact triple icon (chain+token+pair).
 *
 * Logging uses [UI][POSITIONS][...] tags.
 */
@Component({
    standalone: true,
    selector: 'positions-table',
    imports: [AgGridAngular, DialogModule, ButtonModule, JsonPipe],
    templateUrl: './positions-table.component.html',
})
export class PositionsTableComponent {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly webSocketService = inject(WebSocketService);
    private readonly defiIconService = inject(DefiIconsService);
    private readonly numberFormattingService = inject(NumberFormattingService);

    public readonly positionsRowData = computed<any[]>(() => {
        const rows = this.webSocketService.positions() ?? [];
        return Array.isArray(rows) ? [...rows] : [];
    });

    // Modal state
    public readonly detailsVisible = signal<boolean>(false);
    public readonly selectedRow = signal<any | null>(null);

    public openDetails(row: any): void {
        this.selectedRow.set(row);
        this.detailsVisible.set(true);
        console.info('[UI][POSITIONS][DETAILS] open', {
            symbol: row?.symbol,
            chain: row?.chain,
            tokenAddress: row?.address ?? row?.tokenAddress,
            pairAddress: row?.pairAddress,
        });
    }

    public readonly columnDefinitions: ColDef[] = [
        {
            headerName: 'Symbol',
            field: 'symbol',
            sortable: true,
            filter: true,
            // Use triple icon renderer (chain + token + pair)
            cellRenderer: this.defiIconService.tokenChainPairChipRenderer,
            comparator: (a, b) => String(a ?? '').localeCompare(String(b ?? ''), undefined, { sensitivity: 'base' }),
            flex: 1.6,
        },
        {
            headerName: 'Open date',
            field: 'open_date',
            sortable: true,
            filter: 'agDateColumnFilter',
            valueGetter: (p: ValueGetterParams) => p.data?.opened_at ?? null,
            cellClass: 'whitespace-nowrap',
            flex: 1.4,
        },
        {
            headerName: 'Quantity',
            field: 'qty',
            type: 'numericColumn',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatNumber(p.value, 2, 4),
            cellClass: 'text-right whitespace-nowrap',
            flex: 1.3,
        },
        {
            headerName: 'Entry',
            field: 'entry',
            type: 'numericColumn',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
            cellClass: 'text-right whitespace-nowrap',
            flex: 1.1,
        },
        {
            headerName: 'TP1',
            field: 'tp1',
            type: 'numericColumn',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
            cellClass: 'text-right whitespace-nowrap',
            flex: 1.1,
        },
        {
            headerName: 'TP2',
            field: 'tp2',
            type: 'numericColumn',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
            cellClass: 'text-right whitespace-nowrap',
            flex: 1.1,
        },
        {
            headerName: 'Stop',
            field: 'stop',
            type: 'numericColumn',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueFormatter: (p: ValueFormatterParams) => this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
            cellClass: 'text-right whitespace-nowrap',
            flex: 1.1,
        },
        {
            headerName: 'Δ %',
            colId: 'deltaPercent',
            sortable: true,
            filter: 'agNumberColumnFilter',
            valueGetter: (p: ValueGetterParams) => {
                // Primary: WS-enriched field from poseidon.zip
                const enriched = this.numberFormattingService.toNumberSafe(p.data?._changePct);
                if (enriched !== null) {
                    return enriched;
                }

                // Fallback: compute from last_price and entry
                const last = this.numberFormattingService.toNumberSafe(p.data?.last_price);
                const entry = this.numberFormattingService.toNumberSafe(p.data?.entry);
                if (last === null || entry === null || entry === 0) {
                    return null;
                }
                return ((last - entry) / Math.abs(entry)) * 100;
            },
            valueFormatter: (p: ValueFormatterParams) =>
                p.value == null ? '—' : `${this.numberFormattingService.formatNumber(p.value, 2, 2)}%`,
            cellClassRules: {
                'pct-up': (p) => (p.value ?? 0) > 0,
                'pct-down': (p) => (p.value ?? 0) < 0,
            },
            cellClass: 'text-right whitespace-nowrap',
            flex: 0.9,
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
                }
                return (
                    '<span class="' +
                    colorClass +
                    ' saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">' +
                    p.value +
                    '</span>'
                );
            },
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
            flex: 1.2,
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
        suppressHeaderMenuButton: false,
        flex: 1,
    };
}
