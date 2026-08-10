import type { TradingCortexModelRole, TradingShadowingVerdictChronicleCortexModelRolloutPayload } from '../../../../core/models';
import type { ChronicleChartModel, CortexModelRolloutAnnotationBundle, SciChartModule } from '../data/trading-shadowing-verdict-chronicle.models';
import { parseIsoTimestampToEpochMilliseconds } from '../data/trading-shadowing-verdict-chronicle-arrays.utils';
import { CHRONICLE_METRIC_COLORS } from '../data/trading-shadowing-verdict-chronicle-metrics.catalog';
import { raiseChronicleGateThresholdAnnotations } from './trading-shadowing-verdict-chronicle-golden-zone.utils';

const CORTEX_ROLLOUT_LABEL_Y_RELATIVE = 0.96;
const CORTEX_ROLLOUT_LABEL_X_SHIFT = 0;
const CORTEX_ROLLOUT_LABEL_Y_SHIFT = -6;

type CortexRolloutRolePalette = {
    text: string;
    stroke: string;
    line: string;
    fill: string;
};

function resolveCortexRolloutRolePalette(modelRole: TradingCortexModelRole): CortexRolloutRolePalette {
    if (modelRole === 'CHAMPION') {
        return {
            text: CHRONICLE_METRIC_COLORS.cortexRolloutChampionText,
            stroke: CHRONICLE_METRIC_COLORS.cortexRolloutChampionStroke,
            line: CHRONICLE_METRIC_COLORS.cortexRolloutChampionLine,
            fill: CHRONICLE_METRIC_COLORS.cortexRolloutChampionFill
        };
    }
    if (modelRole === 'CHALLENGER') {
        return {
            text: CHRONICLE_METRIC_COLORS.cortexRolloutChallengerText,
            stroke: CHRONICLE_METRIC_COLORS.cortexRolloutChallengerStroke,
            line: CHRONICLE_METRIC_COLORS.cortexRolloutChallengerLine,
            fill: CHRONICLE_METRIC_COLORS.cortexRolloutChallengerFill
        };
    }
    return {
        text: CHRONICLE_METRIC_COLORS.cortexRolloutRetiredText,
        stroke: CHRONICLE_METRIC_COLORS.cortexRolloutRetiredStroke,
        line: CHRONICLE_METRIC_COLORS.cortexRolloutRetiredLine,
        fill: CHRONICLE_METRIC_COLORS.cortexRolloutRetiredFill
    };
}

export function filterCortexRolloutsForBucketWindow(
    rollouts: TradingShadowingVerdictChronicleCortexModelRolloutPayload[],
    bucketFromIso: string,
    bucketToIso: string
): TradingShadowingVerdictChronicleCortexModelRolloutPayload[] {
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

function buildCortexRolloutAnnotationLines(rollout: TradingShadowingVerdictChronicleCortexModelRolloutPayload): string {
    const modelVersion = truncateRolloutToken(rollout.model_version, 28);
    const featureSetVersion = truncateRolloutToken(rollout.feature_set_version, 28);
    const trainingCount = formatRolloutRecordCount(rollout.training_record_count);
    const validationCount = formatRolloutRecordCount(rollout.validation_record_count);
    const accuracyPercent = Math.round(rollout.success_probability_accuracy * 100);
    return [
        `CORTEX · ${rollout.model_role}`,
        `model ${modelVersion}`,
        `feat ${featureSetVersion} · ${trainingCount}/${validationCount} · ${accuracyPercent}%`
    ].join('\n');
}

function escapeSvgText(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function buildCortexRolloutLabelSvg(rollout: TradingShadowingVerdictChronicleCortexModelRolloutPayload): string {
    const [title, model, details] = buildCortexRolloutAnnotationLines(rollout).split('\n');
    const width = 190;
    const height = 44;
    const originX = 0;
    const palette = resolveCortexRolloutRolePalette(rollout.model_role);
    return `
        <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" style="overflow:visible;pointer-events:none">
            <g transform="rotate(45 ${originX} ${height})">
                <rect x="0.5" y="0.5" width="${width - 1}" height="${height - 1}" rx="5" fill="${palette.fill}" stroke="${palette.stroke}" stroke-width="1" />
                <text x="7" y="14" fill="${palette.text}" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10" font-weight="900">${escapeSvgText(title ?? '')}</text>
                <text x="7" y="26" fill="${palette.text}" opacity="0.92" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="10" font-weight="700">${escapeSvgText(model ?? '')}</text>
                <text x="7" y="38" fill="${palette.text}" opacity="0.82" font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" font-size="9" font-weight="700">${escapeSvgText(details ?? '')}</text>
            </g>
        </svg>
    `;
}

function createCortexRolloutBundle(
    sci: SciChartModule,
    rollout: TradingShadowingVerdictChronicleCortexModelRolloutPayload
): CortexModelRolloutAnnotationBundle {
    const { VerticalLineAnnotation, CustomAnnotation, EAnnotationLayer, ECoordinateMode, EVerticalAnchorPoint, EHorizontalAnchorPoint } = sci;
    const isVisible = true;
    const palette = resolveCortexRolloutRolePalette(rollout.model_role);

    const verticalLine = new VerticalLineAnnotation({
        x1: rollout.activated_at_milliseconds,
        xAxisId: 'xTime',
        stroke: palette.line,
        strokeThickness: 2,
        strokeDashArray: [4, 5],
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
        svgString: buildCortexRolloutLabelSvg(rollout)
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
    rollouts: TradingShadowingVerdictChronicleCortexModelRolloutPayload[] | undefined,
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
