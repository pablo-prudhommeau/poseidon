import type { DefiIconsService } from '../../../../core/defi-icons.service';
import { CHRONICLE_DEFAULT_VISIBLE_SERIES } from '../data/trading-shadowing-verdict-chronicle-metrics.catalog';
import { CHRONICLE_SELL_PATH_TOKEN_ICON_SIZE_PIXELS, pickChronicleSellPathTokenIconAnchor } from '../data/trading-shadowing-verdict-chronicle-sell-path.utils';
import { CHRONICLE_SERIES } from '../data/trading-shadowing-verdict-chronicle-series-names';
import type { ChronicleCartesianPoint, ChronicleChartModel } from '../data/trading-shadowing-verdict-chronicle.models';

const SELL_PATH_TOKEN_ICON_GAP_PIXELS = 4;
const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const XLINK_NAMESPACE = 'http://www.w3.org/1999/xlink';
const TOKEN_ICON_LAYER_ID = 'chronicle-sell-path-token-icons';

let sellPathTokenIconSyncGeneration = 0;

interface ChronicleSellPathTokenIconPlacement {
    group: SVGGElement;
    image: SVGImageElement;
    missing: SVGGElement;
    hasSource: boolean | null;
    seriesName: string;
    seriesVisible: boolean;
    x: number;
    y: number;
}

interface ChronicleSellPathTokenIconLayer {
    group: SVGGElement;
    icons: ChronicleSellPathTokenIconPlacement[];
    dirty: boolean;
    disposed: boolean;
}

const sellPathTokenIconLayers = new WeakMap<ChronicleChartModel['sciChartSurface'], ChronicleSellPathTokenIconLayer>();

function usableSellPathTokenIconSource(source: string | null): string | null {
    if (!source || source.startsWith('data:')) {
        return null;
    }
    return source;
}

function resolveSellPathSeriesVisible(model: ChronicleChartModel, seriesName: string): boolean {
    const bundles =
        seriesName === CHRONICLE_SERIES.winnerSellPath ? model.profitableSellPathSegmentBundles : model.lossSellPathSegmentBundles;
    if (bundles.length > 0) {
        return bundles[0].series.isVisible === true;
    }
    return CHRONICLE_DEFAULT_VISIBLE_SERIES.includes(seriesName);
}

function resolvePercentageAxis(model: ChronicleChartModel) {
    return model.sciChartSurface.yAxes.getById('yPct');
}

function ensureSellPathTokenIconLayer(model: ChronicleChartModel): ChronicleSellPathTokenIconLayer {
    const existingLayer = sellPathTokenIconLayers.get(model.sciChartSurface);
    if (existingLayer) {
        return existingLayer;
    }
    const svgRoot = model.sciChartSurface.domSvgContainer;
    const group = document.createElementNS(SVG_NAMESPACE, 'g');
    group.setAttribute('id', TOKEN_ICON_LAYER_ID);
    group.setAttribute('style', 'pointer-events:none;opacity:0.92');
    const defs = document.createElementNS(SVG_NAMESPACE, 'defs');
    const clipPath = document.createElementNS(SVG_NAMESPACE, 'clipPath');
    clipPath.setAttribute('id', `${TOKEN_ICON_LAYER_ID}-clip`);
    clipPath.setAttribute('clipPathUnits', 'objectBoundingBox');
    const circle = document.createElementNS(SVG_NAMESPACE, 'circle');
    circle.setAttribute('cx', '0.5');
    circle.setAttribute('cy', '0.5');
    circle.setAttribute('r', '0.5');
    clipPath.appendChild(circle);
    defs.appendChild(clipPath);
    group.appendChild(defs);
    svgRoot.insertBefore(group, svgRoot.firstChild);
    const layer: ChronicleSellPathTokenIconLayer = { group, icons: [], dirty: true, disposed: false };
    const markDirty = (): void => {
        if (layer.disposed) {
            return;
        }
        layer.dirty = true;
    };
    model.xAxis.visibleRangeChanged.subscribe(markDirty);
    resolvePercentageAxis(model)?.visibleRangeChanged.subscribe(markDirty);
    model.sciChartSurface.rendered.subscribe(() => {
        if (layer.disposed || !layer.dirty) {
            return;
        }
        layer.dirty = false;
        positionSellPathTokenIcons(model, layer);
    });
    sellPathTokenIconLayers.set(model.sciChartSurface, layer);
    return layer;
}

function positionSellPathTokenIcons(model: ChronicleChartModel, layer: ChronicleSellPathTokenIconLayer): void {
    const yAxis = resolvePercentageAxis(model);
    const xCalculator = model.xAxis.getCurrentCoordinateCalculator();
    const yCalculator = yAxis?.getCurrentCoordinateCalculator();
    if (!xCalculator || !yCalculator) {
        layer.dirty = true;
        return;
    }
    const pixelRatio = model.sci.DpiHelper.PIXEL_RATIO || 1;
    const origin = model.sciChartSurface.getCoordSvgTranslation();
    const originX = origin.x / pixelRatio;
    const originY = origin.y / pixelRatio;
    const visibleX = model.xAxis.visibleRange;
    const size = CHRONICLE_SELL_PATH_TOKEN_ICON_SIZE_PIXELS;
    let awaitingCoordinates = false;
    for (const icon of layer.icons) {
        const insideX = !!visibleX && icon.x >= visibleX.min && icon.x <= visibleX.max;
        if (!icon.seriesVisible || !insideX) {
            icon.group.style.display = 'none';
            continue;
        }
        const deviceX = xCalculator.getCoordinate(icon.x);
        const deviceY = yCalculator.getCoordinate(icon.y);
        if (!Number.isFinite(deviceX) || !Number.isFinite(deviceY)) {
            awaitingCoordinates = true;
            icon.group.style.display = 'none';
            continue;
        }
        const left = originX + deviceX / pixelRatio - size / 2;
        const top = originY + deviceY / pixelRatio - size - SELL_PATH_TOKEN_ICON_GAP_PIXELS;
        icon.group.style.display = '';
        icon.group.setAttribute('transform', `translate(${left} ${top})`);
        icon.image.style.display = icon.hasSource === true ? '' : 'none';
        icon.missing.style.display = icon.hasSource === false ? '' : 'none';
    }
    if (awaitingCoordinates) {
        layer.dirty = true;
    }
}

function createSellPathTokenIconNode(source: string | null): Pick<ChronicleSellPathTokenIconPlacement, 'group' | 'image' | 'missing' | 'hasSource'> {
    const size = CHRONICLE_SELL_PATH_TOKEN_ICON_SIZE_PIXELS;
    const group = document.createElementNS(SVG_NAMESPACE, 'g');
    const image = document.createElementNS(SVG_NAMESPACE, 'image');
    image.setAttribute('x', '0');
    image.setAttribute('y', '0');
    image.setAttribute('width', `${size}`);
    image.setAttribute('height', `${size}`);
    image.setAttribute('clip-path', `url(#${TOKEN_ICON_LAYER_ID}-clip)`);
    image.setAttribute('preserveAspectRatio', 'xMidYMid slice');
    image.style.display = 'none';
    const missing = createMissingSellPathTokenIcon(size);
    group.append(image, missing);
    const hasSource = source ? true : null;
    if (source) {
        image.setAttribute('href', source);
        image.setAttributeNS(XLINK_NAMESPACE, 'href', source);
    }
    return { group, image, missing, hasSource };
}

function createMissingSellPathTokenIcon(size: number): SVGGElement {
    const mark = document.createElementNS(SVG_NAMESPACE, 'g');
    mark.style.display = 'none';
    const circle = document.createElementNS(SVG_NAMESPACE, 'circle');
    circle.setAttribute('cx', `${size / 2}`);
    circle.setAttribute('cy', `${size / 2}`);
    circle.setAttribute('r', `${size / 2 - 0.7}`);
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', 'rgb(186, 196, 208)');
    circle.setAttribute('stroke-opacity', '0.72');
    circle.setAttribute('stroke-width', '0.55');
    circle.setAttribute('stroke-linecap', 'round');
    circle.setAttribute('stroke-dasharray', '0.95 1.35');
    const glyph = document.createElementNS(SVG_NAMESPACE, 'g');
    glyph.setAttribute('transform', `scale(${size / 16})`);
    const questionMark = document.createElementNS(SVG_NAMESPACE, 'text');
    questionMark.setAttribute('x', '8');
    questionMark.setAttribute('y', '8');
    questionMark.setAttribute('text-anchor', 'middle');
    questionMark.setAttribute('dominant-baseline', 'central');
    questionMark.setAttribute('font-family', 'Inter, Segoe UI, sans-serif');
    questionMark.setAttribute('font-size', '9');
    questionMark.setAttribute('font-weight', '500');
    questionMark.setAttribute('fill', 'rgb(186, 196, 208)');
    questionMark.setAttribute('fill-opacity', '0.9');
    questionMark.textContent = '?';
    glyph.append(questionMark);
    mark.append(circle, glyph);
    return mark;
}

function appendSellPathTokenIcons(
    model: ChronicleChartModel,
    layer: ChronicleSellPathTokenIconLayer,
    defiIconsService: DefiIconsService,
    paths: ChronicleCartesianPoint[][],
    seriesName: string,
    generation: number
): void {
    const seriesVisible = resolveSellPathSeriesVisible(model, seriesName);
    for (const path of paths) {
        const anchor = pickChronicleSellPathTokenIconAnchor(path);
        if (!anchor) {
            continue;
        }
        const cachedSource = usableSellPathTokenIconSource(defiIconsService.peekTokenIconSource(anchor.blockchainNetwork, anchor.tokenAddress));
        const node = createSellPathTokenIconNode(cachedSource);
        layer.group.appendChild(node.group);
        const placement: ChronicleSellPathTokenIconPlacement = {
            ...node,
            seriesName,
            seriesVisible,
            x: anchor.x,
            y: anchor.y
        };
        node.image.addEventListener('error', () => {
            if (generation !== sellPathTokenIconSyncGeneration || layer.disposed || placement.hasSource !== true) {
                return;
            }
            placement.hasSource = false;
            layer.dirty = true;
        });
        layer.icons.push(placement);
        if (cachedSource) {
            continue;
        }
        void defiIconsService
            .resolveTokenIconSource(anchor.blockchainNetwork, anchor.tokenAddress, anchor.tokenSymbol)
            .then((source) => {
                if (generation !== sellPathTokenIconSyncGeneration || layer.disposed) {
                    return;
                }
                const iconSource = usableSellPathTokenIconSource(source);
                placement.hasSource = !!iconSource;
                if (iconSource) {
                    placement.image.setAttribute('href', iconSource);
                    placement.image.setAttributeNS(XLINK_NAMESPACE, 'href', iconSource);
                }
                layer.dirty = true;
            })
            .catch(() => {
                if (generation !== sellPathTokenIconSyncGeneration || layer.disposed) {
                    return;
                }
                placement.hasSource = false;
                layer.dirty = true;
            });
    }
}

export function clearChronicleSellPathTokenIconAnnotations(model: ChronicleChartModel): void {
    const layer = sellPathTokenIconLayers.get(model.sciChartSurface);
    if (!layer) {
        return;
    }
    for (const icon of layer.icons) {
        icon.group.remove();
    }
    layer.icons = [];
}

export function synchronizeChronicleSellPathTokenIconAnnotations(
    model: ChronicleChartModel,
    defiIconsService: DefiIconsService,
    profitablePaths: ChronicleCartesianPoint[][],
    lossPaths: ChronicleCartesianPoint[][]
): void {
    const generation = ++sellPathTokenIconSyncGeneration;
    const layer = ensureSellPathTokenIconLayer(model);
    clearChronicleSellPathTokenIconAnnotations(model);
    appendSellPathTokenIcons(model, layer, defiIconsService, profitablePaths, CHRONICLE_SERIES.winnerSellPath, generation);
    appendSellPathTokenIcons(model, layer, defiIconsService, lossPaths, CHRONICLE_SERIES.loserSellPath, generation);
    layer.dirty = true;
    positionSellPathTokenIcons(model, layer);
}

export function setChronicleSellPathTokenIconVisibility(model: ChronicleChartModel, seriesName: string, isVisible: boolean): void {
    const layer = sellPathTokenIconLayers.get(model.sciChartSurface);
    if (!layer) {
        return;
    }
    for (const icon of layer.icons) {
        if (icon.seriesName === seriesName) {
            icon.seriesVisible = isVisible;
        }
    }
    layer.dirty = true;
    positionSellPathTokenIcons(model, layer);
}
