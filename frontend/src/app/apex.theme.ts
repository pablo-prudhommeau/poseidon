import {ApexOptions} from 'apexcharts';

export function apexDarkBase(): ApexOptions {
    return {
        theme: {mode: 'dark'},
        chart: {
            background: 'transparent',
            foreColor: '#cbd5e1',
            toolbar: {show: true, tools: {download: true, selection: false, zoom: true, zoomin: true, zoomout: true, pan: false, reset: true}}
        },
        grid: {borderColor: '#243043', strokeDashArray: 3},
        dataLabels: {enabled: false},
        tooltip: {theme: 'dark'},
        legend: {labels: {colors: '#cbd5e1'}},
        stroke: {width: 2},
        fill: {opacity: 0.35}
    };
}