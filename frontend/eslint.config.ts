import eslint from '@eslint/js';
import angular from 'angular-eslint';
import tseslint from 'typescript-eslint';

export default tseslint.config(
    {
        ignores: ['.angular/**', 'dist/**', 'coverage/**']
    },
    {
        files: ['src/**/*.ts'],
        extends: [eslint.configs.recommended, ...tseslint.configs.recommended, ...angular.configs.tsRecommended],
        processor: angular.processInlineTemplates,
        plugins: {
            perfectionist: require('eslint-plugin-perfectionist')
        },
        rules: {
            '@angular-eslint/component-selector': 'off',
            '@angular-eslint/directive-selector': 'off',
            '@angular-eslint/prefer-inject': 'off',
            '@angular-eslint/no-empty-lifecycle-method': 'off',
            '@typescript-eslint/no-explicit-any': 'off',
            '@typescript-eslint/no-unused-vars': 'off',
            'no-empty': 'off',
            'prefer-const': 'off',
            'perfectionist/sort-classes': [
                'error',
                {
                    type: 'alphabetical',
                    order: 'asc',
                    ignoreCase: true,
                    customGroups: [
                        {
                            groupName: 'angular-lifecycle',
                            elementNamePattern:
                                '^(ngOnChanges|ngOnInit|ngDoCheck|ngAfterContentInit|ngAfterContentChecked|ngAfterViewInit|ngAfterViewChecked|ngOnDestroy)$'
                        }
                    ],
                    groups: [
                        'index-signature',
                        'public-static-property',
                        'protected-static-property',
                        'private-static-property',
                        'public-decorated-property',
                        'protected-decorated-property',
                        'private-decorated-property',
                        'public-property',
                        'protected-property',
                        'private-property',
                        'constructor',
                        'angular-lifecycle',
                        'public-get-method',
                        'public-set-method',
                        'protected-get-method',
                        'protected-set-method',
                        'private-get-method',
                        'private-set-method',
                        'public-method',
                        'protected-method',
                        'private-method',
                        'public-static-method',
                        'protected-static-method',
                        'private-static-method',
                        'unknown'
                    ]
                }
            ]
        }
    },
    {
        files: ['src/**/*.html'],
        extends: [...angular.configs.templateRecommended, ...angular.configs.templateAccessibility],
        rules: {
            '@angular-eslint/template/click-events-have-key-events': 'off',
            '@angular-eslint/template/elements-content': 'off',
            '@angular-eslint/template/eqeqeq': 'off',
            '@angular-eslint/template/interactive-supports-focus': 'off'
        }
    }
);
