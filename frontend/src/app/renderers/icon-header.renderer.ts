import {CommonModule} from '@angular/common';
import {Component} from '@angular/core';
import {IHeaderAngularComp} from 'ag-grid-angular';
import {IHeaderParams} from 'ag-grid-community';

type IconHeaderConfig = {
    iconClass?: string;
    hideLabel?: boolean;
    alignRight?: boolean;
    alignCenter?: boolean;
};

@Component({
    standalone: true,
    selector: 'app-icon-header-renderer',
    imports: [CommonModule],
    styles: [
        `
			:host {
				display: block;
				width: 100%;
				max-width: 100%;
				min-width: 0;
				box-sizing: border-box;
			}
        `
    ],
    template: `
		<div
				class="flex items-center gap-2 text-slate-400 select-none w-full min-h-[1.25rem]"
				[ngClass]="headerRowClass">
			<i class="fas {{ iconClass }} shrink-0 opacity-90 text-[0.78rem]" aria-hidden="true"></i>
			@if (!hideLabel) {
				<span class="truncate font-extrabold tracking-wide text-slate-200 uppercase text-[12px] leading-tight">{{ labelUpper }}</span>
			}
		</div>
    `
})
export class IconHeaderRendererComponent implements IHeaderAngularComp {
    public iconClass = 'fa-circle';
    public labelUpper = '';
    public hideLabel = false;
    public headerRowClass: Record<string, boolean> = {};

    public agInit(params: IHeaderParams): void {
        const headerParams = (params.column?.getColDef().headerComponentParams ?? {}) as IconHeaderConfig;
        const raw = headerParams.iconClass ?? 'fa-circle';
        this.iconClass = raw.startsWith('fa-') ? raw : `fa-${raw}`;
        this.hideLabel = Boolean(headerParams.hideLabel);
        const alignCenter = Boolean(headerParams.alignCenter);
        const alignRight = Boolean(headerParams.alignRight);
        this.labelUpper = (params.displayName ?? '').toUpperCase();
        this.headerRowClass = this.hideLabel
            ? {'justify-center': true, 'w-full': true}
            : alignCenter
                ? {'justify-center': true, 'w-full': true}
                : alignRight
                    ? {'justify-end': true, 'w-full': true}
                    : {'justify-start': true, 'min-w-0': true};
    }

    public refresh(params: IHeaderParams): boolean {
        this.agInit(params);
        return true;
    }
}
