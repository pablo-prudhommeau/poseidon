import { DecimalPipe, NgClass } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
    standalone: true,
    selector: 'pnl-badge',
    imports: [DecimalPipe, NgClass],
    templateUrl: './pnl-badge.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class PnlBadgeComponent {
    public readonly value = input<number>(0);

    public readonly absoluteFinancialAmount = computed(() => {
        const currentAmount = this.value() ?? 0;
        return Math.abs(currentAmount);
    });

    public readonly currencySymbol = input<string>('$');

    public readonly isPositiveAmount = computed(() => {
        const currentAmount = this.value() ?? 0;
        return currentAmount >= 0;
    });
}
