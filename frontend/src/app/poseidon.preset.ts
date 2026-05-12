import { definePreset } from '@primeuix/themes';
import Aura from '@primeuix/themes/aura';
import type { ComponentsDesignTokens } from '@primeuix/themes/types';

const componentsDesignTokens: ComponentsDesignTokens = {
    button: {
        root: {
            gap: '0.25rem',
            paddingX: '0.45rem',
            paddingY: '0.30rem',
            borderRadius: '0.50rem',
            iconOnlyWidth: '1.50rem',
            label: {
                fontWeight: '500'
            },
            sm: {
                fontSize: '0.75rem',
                paddingX: '0.40rem',
                paddingY: '0.27rem',
                iconOnlyWidth: '1.45rem'
            },
            lg: {
                fontSize: '0.95rem',
                paddingX: '0.70rem',
                paddingY: '0.45rem',
                iconOnlyWidth: '1.80rem'
            }
        },
        css: ({ dt }) => `
          .p-button.p-button-icon-only  { 
            line-height: 1.05rem;
          }
          .p-button-sm.p-button-icon-only  { 
            line-height: 0.90rem;
          }
          .p-button-lg.p-button-icon-only  { 
            line-height: 1.20rem;
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
    semantic: {
        primary: {
            50: '{blue.50}',
            100: '{blue.100}',
            200: '{blue.200}',
            300: '{blue.300}',
            400: '{blue.400}',
            500: '{blue.500}',
            600: '{blue.600}',
            700: '{blue.700}',
            800: '{blue.800}',
            900: '{blue.900}',
            950: '{blue.950}'
        }
    },
    components: componentsDesignTokens
});

export default PoseidonPreset;
