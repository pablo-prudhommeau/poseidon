import type { DefiIconsService } from '../../../../core/defi-icons.service';
import type { ChronicleCartesianPoint, ChronicleChartModel } from '../data/trading-shadowing-verdict-chronicle.models';
import { deleteChronicleAnnotationSafely } from './trading-shadowing-verdict-chronicle-annotation-detach.utils';

export function clearChronicleSellPathTokenIconAnnotations(model: ChronicleChartModel): void {
    const annotations = model.sciChartSurface.annotations;
    for (const bundle of model.sellPathTokenIconAnnotations) {
        deleteChronicleAnnotationSafely(annotations, bundle.annotation);
    }
    model.sellPathTokenIconAnnotations = [];
}

export function synchronizeChronicleSellPathTokenIconAnnotations(
    model: ChronicleChartModel,
    _defiIconsService: DefiIconsService,
    _profitablePaths: ChronicleCartesianPoint[][],
    _lossPaths: ChronicleCartesianPoint[][]
): void {
    clearChronicleSellPathTokenIconAnnotations(model);
}

export function setChronicleSellPathTokenIconVisibility(model: ChronicleChartModel, seriesName: string, isVisible: boolean): void {
    for (const bundle of model.sellPathTokenIconAnnotations) {
        if (bundle.seriesName === seriesName) {
            bundle.annotation.isHidden = !isVisible;
        }
    }
}
