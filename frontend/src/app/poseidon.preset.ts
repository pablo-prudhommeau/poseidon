import {definePreset} from '@primeuix/themes';
import Aura from '@primeuix/themes/aura';
import type {ComponentsDesignTokens} from '@primeuix/themes/types';

/**
 * PoseidonPreset — Aura compact + fix d’alignement des boutons.
 * - Icon-only: carrés garantis (width == height).
 * - Label/icon: centrés, line-height neutralisé.
 * - Dans AG Grid: alignement visuel sans styles globaux additionnels.
 */
const componentsDesignTokens: ComponentsDesignTokens = {
    button: {
        root: {
            gap: '0.25rem',
            paddingX: '0.45rem',
            paddingY: '0.30rem',
            borderRadius: '0.50rem',
            iconOnlyWidth: '1.50rem',
            label: {fontWeight: '500'},
            sm: {
                fontSize: '0.75rem',
                paddingX: '0.35rem',
                paddingY: '0.22rem',
                iconOnlyWidth: '1.35rem'
            },
            lg: {
                fontSize: '0.95rem',
                paddingX: '0.70rem',
                paddingY: '0.45rem',
                iconOnlyWidth: '1.80rem'
            }
        },
        // 🔧 Correctifs d’alignement et de line-height, scoped via le preset
        css: ({ dt }) => `
          /* Ne pas laisser le line-height gonfler la hauteur */
          .p-button { 
            line-height: 1;
            /* Centrage horizontal/vertical de l'icône et/ou du label */
            display: inline-grid;
            grid-auto-flow: column;
            place-items: center;
            gap: ${dt('button.root.gap')};
            vertical-align: middle; /* utile dans les cellules AG Grid */
          }

          /* Icon-only: carré strict basé sur les tokens */
          .p-button.p-button-icon-only {
            inline-size: ${dt('button.root.iconOnlyWidth')};
            block-size: ${dt('button.root.iconOnlyWidth')};
            min-inline-size: ${dt('button.root.iconOnlyWidth')};
            min-block-size: ${dt('button.root.iconOnlyWidth')};
            padding: 0;
            aspect-ratio: 1 / 1;
          }

          /* Variante small: carré plus serré */
          .p-button.p-button-sm.p-button-icon-only {
            inline-size: ${dt('button.root.sm.iconOnlyWidth')};
            block-size: ${dt('button.root.sm.iconOnlyWidth')};
            min-inline-size: ${dt('button.root.sm.iconOnlyWidth')};
            min-block-size: ${dt('button.root.sm.iconOnlyWidth')};
          }

          /* Le texte ne doit pas réintroduire de hauteur */
          .p-button .p-button-label,
          .p-button .p-button-icon {
            line-height: 1;
            margin: 0;
          }

          /* Petit coup de pouce visuel uniquement à l'intérieur d'AG Grid */
          .ag-theme-quartz .ag-cell .p-button,
          .ag-theme-quartz-dark .ag-cell .p-button {
            vertical-align: middle;
          }
        `
    },
    inputtext: {
        root: {
            paddingX: '0.50rem',
            paddingY: '0.28rem',
            borderRadius: '0.50rem',
            sm: { fontSize: '0.80rem', paddingX: '0.45rem', paddingY: '0.22rem' },
            lg: { fontSize: '0.95rem', paddingX: '0.65rem', paddingY: '0.35rem' }
        }
    },
    select: {
        root: {
            paddingX: '0.50rem',
            paddingY: '0.28rem',
            borderRadius: '0.50rem',
            sm: { fontSize: '0.80rem', paddingX: '0.45rem', paddingY: '0.22rem' }
        }
    },
    dialog: {
        header: { padding: '0.50rem 0.75rem', gap: '0.40rem' },
        footer: { padding: '0.50rem 0.75rem', gap: '0.40rem' }
    },
    toolbar: {
        root: { padding: '0.40rem 0.60rem', gap: '0.50rem' }
    }
};

const PoseidonPreset = definePreset(Aura, {
    components: componentsDesignTokens
});

export default PoseidonPreset;
