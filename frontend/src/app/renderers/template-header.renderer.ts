import { CommonModule } from '@angular/common';
import { Component, TemplateRef } from '@angular/core';
import { IHeaderAngularComp } from 'ag-grid-angular';
import { IHeaderParams } from 'ag-grid-community';

/**
 * Angular header renderer that renders a provided TemplateRef with a header context.
 * Context:
 *  - $implicit: displayName
 *  - displayName, enableMenu, showColumnMenu, column
 *  - params: full IHeaderParams
 */
@Component({
    standalone: true,
    selector: 'app-template-header-renderer',
    imports: [CommonModule],
    template: `
    <ng-container
      *ngIf="template"
      [ngTemplateOutlet]="template"
      [ngTemplateOutletContext]="context">
    </ng-container>
  `,
})
export class TemplateHeaderRendererComponent implements IHeaderAngularComp {
    public template?: TemplateRef<unknown>;
    public context: Record<string, unknown> = {};

    agInit(params: IHeaderParams & { template?: TemplateRef<unknown> }): void {
        this.template = params.template;
        this.context = {
            $implicit: params.displayName,
            displayName: params.displayName,
            enableMenu: params.enableMenu,
            showColumnMenu: (sourceEl: HTMLElement) => params.showColumnMenu(sourceEl),
            column: params.column,
            params,
        };
    }

    refresh(params: IHeaderParams & { template?: TemplateRef<unknown> }): boolean {
        this.agInit(params);
        return true;
    }
}
