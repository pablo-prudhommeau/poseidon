import type { ShadowVerdictChronicleCortexModelRolloutPayload } from '../../../../core/models';
import type { ChronicleChartModel, CortexModelRolloutAnnotationBundle, SciChartModule } from '../data/shadow-verdict-chronicle.models';
import { parseIsoTimestampToEpochMilliseconds } from '../data/shadow-verdict-chronicle-arrays.utils';
import { CHRONICLE_METRIC_COLORS } from '../data/shadow-verdict-chronicle-metrics.catalog';
import { raiseChronicleGateThresholdAnnotations } from './shadow-verdict-chronicle-golden-zone.utils';

const CORTEX_ROLLOUT_LABEL_Y_RELATIVE = 0.96;
const CORTEX_ROLLOUT_LABEL_X_SHIFT = 0;
const CORTEX_ROLLOUT_LABEL_Y_SHIFT = -6;

export function filterCortexRolloutsForBucketWindow(
    rollouts: ShadowVerdictChronicleCortexModelRolloutPayload[],
    bucketFromIso: string,
    bucketToIso: string
): ShadowVerdictChronicleCortexModelRolloutPayload[] {
    const fromMilliseconds = parseIsoTimestampToEpochMilliseconds(bucketFromIso);
    const toMilliseconds = parseIsoTimestampToEpochMilliseconds(bucketToIso);
    if (fromMilliseconds == null || toMilliseconds == null) {
        return rollouts;
    }
    const marginMilliseconds = 60_000;
    return rollouts.filter(
        (rollout) =>
            rollout.activated_at_milliseconds >= fromMilliseconds - marginMilliseconds &&
            rollout.activated_at_milliseconds <= toMilliseconds + marginMilliseconds
    );
}

function formatRolloutRecordCount(count: number): string {
    if (count >= 1_000_000) {
        return `${(count / 1_000_000).toFixed(1)}M`;
    }
    if (count >= 1_000) {
        return `${(count / 1_000).toFixed(1)}k`;
    }
    return `${count}`;
}

function truncateRolloutToken(value: string, maxLength: number): string {
    if (value.length <= maxLength) {
        return value;
    }
    return `${value.slice(0, Math.max(0, maxLength - 1))}…`;
}

function buildCortexRolloutAnnotationLines(rollout: ShadowVerdictChronicleCortexModelRolloutPayload): string {
    const modelVersion = truncateRolloutToken(rollout.model_version, 28);
    const featureSetVersion = truncateRolloutToken(rollout.feature_set_version, 28);
    const trainingCount = formatRolloutRecordCount(rollout.training_record_count);
    const validationCount = formatRolloutRecordCount(rollout.validation_record_count);
    const accuracyPercent = Math.round(rollout.success_probability_accuracy * 100);
    return [`CORTEX ROLLOUT`, `model ${modelVersion}`, `feat ${featureSetVersion} · ${trainingCount}/${validationCount} · ${accuracyPercent}%`].join('\n');
}

function escapeSvgText(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function buildCortexRolloutLabelSvg(rollout: ShadowVerdictChronicleCortexModelRolloutPayload, isActive: boolean): string {
    const [title, model, details] = buildCortexRolloutAnnotationLines(rollout).split('\n');
    const width = 178;
    const height = 34;
    const originX = 0;
    const fill = isActive ? CHRONICLE_METRIC_COLORS.cortexRolloutActiveFill : CHRONICLE_METRIC_COLORS.cortexRolloutInactiveFill;
    const stroke = isActive ? CHRONICLE_METRIC_COLORS.cortexRolloutActiveStroke : CHRONICLE_METRIC_COLORS.cortexRolloutInactiveStroke;
    const textColor = isActive ? CHRONICLE_METRIC_COLORS.cortexRolloutActiveText : CHRONICLE_METRIC_COLORS.cortexRolloutInactiveText;
    return `
        <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" style="overflow:visible;pointer-events:none">
            <g transform="rotate(45 ${originX} ${height})">
                <rect x="0.5" y="0.5" width="${width - 1}" height="${height - 1}" rx="5" fill="${fill}" stroke="${stroke}" stroke-width="1" />
                <text x="6" y="9" fill="${textColor}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="8" font-weight="900">${escapeSvgText(title ?? '')}</text>
                <text x="6" y="20" fill="${textColor}" opacity="0.92" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="8" font-weight="700">${escapeSvgText(model ?? '')}</text>
                <text x="6" y="30" fill="${textColor}" opacity="0.82" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="7" font-weight="700">${escapeSvgText(details ?? '')}</text>
            </g>
        </svg>
    `;
}

function createCortexRolloutBundle(sci: SciChartModule, rollout: ShadowVerdictChronicleCortexModelRolloutPayload): CortexModelRolloutAnnotationBundle {
    const { VerticalLineAnnotation, CustomAnnotation, EAnnotationLayer, ECoordinateMode, EVerticalAnchorPoint, EHorizontalAnchorPoint } = sci;
    const isActive = rollout.is_active;
    const isVisible = true;

    const lineColor = isActive ? CHRONICLE_METRIC_COLORS.cortexRolloutActiveLine : CHRONICLE_METRIC_COLORS.cortexRolloutInactiveLine;

    const verticalLine = new VerticalLineAnnotation({
        x1: rollout.activated_at_milliseconds,
        xAxisId: 'xTime',
        stroke: lineColor,
        strokeThickness: isActive ? 2 : 1.5,
        strokeDashArray: isActive ? [3, 3] : [4, 5],
        showLabel: false,
        opacity: 1,
        isEditable: false,
        isHidden: !isVisible,
        annotationLayer: EAnnotationLayer.AboveChart
    });

    const textLabel = new CustomAnnotation({
        x1: rollout.activated_at_milliseconds,
        y1: CORTEX_ROLLOUT_LABEL_Y_RELATIVE,
        xAxisId: 'xTime',
        yAxisId: 'yPct',
        xCoordinateMode: ECoordinateMode.DataValue,
        yCoordinateMode: ECoordinateMode.Relative,
        xCoordShift: CORTEX_ROLLOUT_LABEL_X_SHIFT,
        yCoordShift: CORTEX_ROLLOUT_LABEL_Y_SHIFT,
        verticalAnchorPoint: EVerticalAnchorPoint.Bottom,
        horizontalAnchorPoint: EHorizontalAnchorPoint.Center,
        isEditable: false,
        isHidden: !isVisible,
        annotationLayer: EAnnotationLayer.AboveChart,
        opacity: 0.96,
        svgString: buildCortexRolloutLabelSvg(rollout, isActive)
    });

    return { verticalLine, textLabel };
}

export function clearCortexModelRolloutAnnotations(model: ChronicleChartModel): void {
    const annotations = model.sciChartSurface.annotations;
    for (const bundle of model.cortexModelRolloutAnnotationBundles) {
        annotations.remove(bundle.verticalLine);
        annotations.remove(bundle.textLabel);
    }
    model.cortexModelRolloutAnnotationBundles = [];
}

export function synchronizeCortexModelRolloutAnnotations(
    model: ChronicleChartModel,
    rollouts: ShadowVerdictChronicleCortexModelRolloutPayload[] | undefined,
    bucketFromIso: string,
    bucketToIso: string
): void {
    clearCortexModelRolloutAnnotations(model);
    if (!rollouts?.length) {
        raiseChronicleGateThresholdAnnotations(model);
        return;
    }

    const visibleRollouts = filterCortexRolloutsForBucketWindow(rollouts, bucketFromIso, bucketToIso);
    const annotations = model.sciChartSurface.annotations;

    for (const rollout of visibleRollouts) {
        const bundle = createCortexRolloutBundle(model.sci, rollout);
        bundle.verticalLine.isHidden = !model.cortexModelRolloutUserVisible;
        bundle.textLabel.isHidden = !model.cortexModelRolloutUserVisible;
        annotations.add(bundle.verticalLine);
        annotations.add(bundle.textLabel);
        model.cortexModelRolloutAnnotationBundles.push(bundle);
    }

    raiseChronicleGateThresholdAnnotations(model);
}
