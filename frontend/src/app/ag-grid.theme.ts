import {colorSchemeDark, themeQuartz} from 'ag-grid-community';

export const balhamDarkThemeCompact = themeQuartz
    .withParams({
        headerHeight: 36,
        borderRadius: 8,
        fontSize: 12,
        rowHeight: 38,
        backgroundColor: 'rgba(0, 0, 0, 0.15)',
        foregroundColor: '#e2e8f0',
        headerBackgroundColor: 'rgba(0, 0, 0, 0.3)',
        headerFontWeight: 700,
        headerFontSize: 10,
        oddRowBackgroundColor: 'rgba(255, 255, 255, 0.02)',
        rowHoverColor: 'rgba(255, 255, 255, 0.05)',
        selectedRowBackgroundColor: 'rgba(255, 255, 255, 0.08)',
        borderColor: 'rgba(255, 255, 255, 0.05)',
        wrapperBorderRadius: 12,
        columnBorder: false,
        cellHorizontalPadding: 12,
        spacing: 4,
    })
    .withPart(colorSchemeDark);
