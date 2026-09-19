import type { SciChartSurface } from 'scichart';
import type { ChronicleChartModel } from '../data/trading-shadowing-verdict-chronicle.models';

type ChronicleAnnotationCollection = ChronicleChartModel['sciChartSurface']['annotations'];

type ChronicleDetachableAnnotation = {
    delete?: () => void;
};

type ChronicleSurfaceAnnotation = {
    invalidateParentCallback?: unknown;
    onDetach: () => void;
    parentSurface?: unknown;
};

type ChronicleDetachAnnotationHost = {
    detachAnnotation?: (annotation: ChronicleSurfaceAnnotation) => void;
    invalidateElement: () => void;
};

type ChronicleHtmlAnnotationInternals = ChronicleDetachableAnnotation & {
    htmlElement?: HTMLElement;
    layerRootProperty?: HTMLElement;
};

function patchedChronicleDetachAnnotation(this: ChronicleDetachAnnotationHost, annotation: ChronicleSurfaceAnnotation): void {
    try {
        annotation.onDetach();
    } catch {}
    annotation.invalidateParentCallback = undefined;
    annotation.parentSurface = undefined;
    try {
        this.invalidateElement();
    } catch {}
}

export function patchChronicleSciChartAnnotationDetach(surface: SciChartSurface): void {
    const detachHost: ChronicleDetachAnnotationHost = surface as unknown as ChronicleDetachAnnotationHost;
    if (typeof detachHost.detachAnnotation !== 'function') {
        return;
    }
    detachHost.detachAnnotation = patchedChronicleDetachAnnotation;
}

function prepareHtmlAnnotationLayerRoot(annotation: ChronicleHtmlAnnotationInternals): void {
    const htmlElement: HTMLElement | undefined = annotation.htmlElement;
    if (!htmlElement) {
        return;
    }
    const dummyLayerRoot: HTMLElement = document.createElement('div');
    const wrapperElement: HTMLElement = htmlElement.parentElement ?? document.createElement('div');
    if (!htmlElement.parentElement) {
        wrapperElement.appendChild(htmlElement);
    }
    dummyLayerRoot.appendChild(wrapperElement);
    annotation.layerRootProperty = dummyLayerRoot;
}

export function detachChronicleAnnotationSafely(annotations: ChronicleAnnotationCollection, annotation: ChronicleDetachableAnnotation | undefined): void {
    if (!annotation) {
        return;
    }
    prepareHtmlAnnotationLayerRoot(annotation as ChronicleHtmlAnnotationInternals);
    try {
        annotations.remove(annotation as never);
    } catch {}
}

export function deleteChronicleAnnotationSafely(annotations: ChronicleAnnotationCollection, annotation: ChronicleDetachableAnnotation | undefined): void {
    detachChronicleAnnotationSafely(annotations, annotation);
    try {
        annotation?.delete?.();
    } catch {}
}

export function addChronicleAnnotationSafely(annotations: ChronicleAnnotationCollection, annotation: ChronicleDetachableAnnotation | undefined): void {
    if (!annotation) {
        return;
    }
    try {
        annotations.add(annotation as never);
    } catch {}
}
