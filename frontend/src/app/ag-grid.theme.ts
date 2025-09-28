import {colorSchemeDarkBlue, themeQuartz} from 'ag-grid-community';

export const balhamDarkThemeCompact = themeQuartz
    .withParams({
        headerHeight: 30,
        borderRadius: 20,
        fontSize: 12,
        rowHeight: 34
    })
    .withPart(colorSchemeDarkBlue);
