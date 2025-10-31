import { CommonModule } from '@angular/common';
import { Component, TemplateRef } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

/**
 * Angular cell renderer that renders a provided TemplateRef with a rich context.
 * Context exposed to the template:
 *  - $implicit: cell value
 *  - value:     cell value
 *  - row:       row data
 *  - data:      row data (alias)
 *  - params:    full ICellRendererParams
 */
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
  `,
})
export class TemplateCellRendererComponent implements ICellRendererAngularComp {
    public template?: TemplateRef<unknown>;
    public context: Record<string, unknown> = {};

    agInit(params: ICellRendererParams & { template?: TemplateRef<unknown> }): void {
        this.template = params.template;
        this.context = {
            $implicit: params.value,
            value: params.value,
            row: params.data,
            data: params.data,
            params,
        };
    }

    refresh(params: ICellRendererParams & { template?: TemplateRef<unknown> }): boolean {
        this.agInit(params);
        return true;
    }
}
