import {CommonModule} from '@angular/common';
import {AfterViewInit, Component, ElementRef, inject, ViewChild} from '@angular/core';
import {ICellRendererAngularComp} from 'ag-grid-angular';
import {ICellRendererParams} from 'ag-grid-community';
import {DefiIconsService} from '../core/defi-icons.service';

@Component({
    standalone: true,
    selector: 'app-symbol-chip-renderer',
    imports: [CommonModule],
    template: `
		<span #host class="inline-flex items-center gap-2"></span>
    `
})
export class SymbolChipRendererComponent implements ICellRendererAngularComp, AfterViewInit {
    private defiIcons = inject(DefiIconsService);

    private params!: ICellRendererParams;
    private renderedEl?: HTMLElement;

    @ViewChild('host', {static: true}) private hostRef!: ElementRef<HTMLElement>;

    agInit(params: ICellRendererParams): void {
        this.params = params;
    }

    ngAfterViewInit(): void {
        this.render();
    }

    refresh(params: ICellRendererParams): boolean {
        this.params = params;
        this.render();
        return true;
    }

    private render(): void {
        try {
            if (this.renderedEl) {
                this.renderedEl.remove();
                this.renderedEl = undefined;
            }
            const chipEl = this.defiIcons.tokenChainChipRenderer(this.params);
            this.hostRef.nativeElement.appendChild(chipEl);
            this.renderedEl = chipEl;
        } catch (error) {
            console.debug('[UI][SYMBOL][RENDER] render error', error);
        }
    }
}
