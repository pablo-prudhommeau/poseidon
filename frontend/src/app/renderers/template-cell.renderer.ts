import { CommonModule } from '@angular/common';
import { Component, TemplateRef } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

@Component({
    standalone: true,
    selector: 'app-template-cell-renderer',
    imports: [CommonModule],
    template: `
		<ng-container
				*ngIf="template"
				[ngTemplateOutlet]="template"
				[ngTemplateOutletContext]="context">
		</ng-container>
    `
})
export class TemplateCellRendererComponent implements ICellRendererAngularComp {
    public context: Record<string, unknown> = {};
    public template?: TemplateRef<unknown>;

    agInit(params: ICellRendererParams & { template?: TemplateRef<unknown> }): void {
        this.template = params.template;
        this.context = {
            $implicit: params.value,
            value: params.value,
            row: params.data,
            data: params.data,
            params
        };
    }

    refresh(params: ICellRendererParams & { template?: TemplateRef<unknown> }): boolean {
        this.agInit(params);
        return true;
    }
}
