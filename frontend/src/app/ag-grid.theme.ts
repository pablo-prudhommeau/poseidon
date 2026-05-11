import {colorSchemeDark, themeQuartz} from 'ag-grid-community';

export const balhamDarkThemeCompact = themeQuartz
    .withParams({
        headerHeight: 36,
        borderRadius: 10,
        fontSize: 12,
        rowHeight: 36,
        backgroundColor: 'rgba(15, 23, 42, 0.45)',
        foregroundColor: '#e2e8f0',
        headerBackgroundColor: 'rgba(0, 0, 0, 0.3)',
        headerFontWeight: 800,
        headerFontSize: 12,
        oddRowBackgroundColor: 'rgba(255, 255, 255, 0.02)',
        rowHoverColor: 'rgba(56, 189, 248, 0.06)',
        selectedRowBackgroundColor: 'rgba(99, 102, 241, 0.12)',
        borderColor: 'rgba(255, 255, 255, 0.06)',
        wrapperBorderRadius: 12,
        columnBorder: false,
        cellHorizontalPadding: 10,
        spacing: 4,
    })
    .withPart(colorSchemeDark);
