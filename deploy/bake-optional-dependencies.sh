#!/bin/sh
set -eu

. /app/deploy/optional-dependencies-pack-versions.sh

OPTIONAL_DEPENDENCIES_ROOT="/app/backend/data/optional-dependencies"
PLAYWRIGHT_BROWSERS_DIRECTORY="${OPTIONAL_DEPENDENCIES_ROOT}/playwright-browsers"
PYTHON_PACKAGES_ROOT="${OPTIONAL_DEPENDENCIES_ROOT}/python-packages"
MARKERS_DIRECTORY="${OPTIONAL_DEPENDENCIES_ROOT}/markers"
RUNTIME_ENVIRONMENT_FILE="${OPTIONAL_DEPENDENCIES_ROOT}/runtime-environment.sh"
OPTIONAL_DEPENDENCIES_BAKE_STAGING_ROOT="/tmp/poseidon-optional-dependencies-bake-staging"
POSEIDON_OPTIONAL_DEPENDENCIES_BAKED_MARKER="/app/.poseidon-optional-dependencies-baked"

_abort_bake() {
    echo "[BAKE][OPTIONAL_DEPENDENCIES][FATAL] $1" >&2
    exit 1
}

_prepare_staging_directory() {
    staging_directory="$1"
    rm -rf "$staging_directory"
    mkdir -p "$staging_directory"
}

_sync_staged_python_packages_to_image() {
    pack_label="$1"
    staging_directory="$2"
    target_directory="$3"

    echo "[BAKE][OPTIONAL_DEPENDENCIES][${pack_label}] Copying staged Python packages into image"
    mkdir -p "$target_directory"
    rm -rf "${target_directory:?}/"*
    cp -a "${staging_directory}/." "${target_directory}/"
    rm -rf "$staging_directory"
}

_write_marker_ok() {
    pack_name="$1"
    version="$2"
    printf '%s' "$version" > "${MARKERS_DIRECTORY}/${pack_name}.ok"
}

_bake_cortex_pack() {
    echo "[BAKE][OPTIONAL_DEPENDENCIES][CORTEX] Baking pack version ${CORTEX_PACK_VERSION}"
    cortex_python_packages_directory="${PYTHON_PACKAGES_ROOT}/${CORTEX_PACK_NAME}"
    cortex_staging_directory="${OPTIONAL_DEPENDENCIES_BAKE_STAGING_ROOT}/${CORTEX_PACK_NAME}"
    mkdir -p "$cortex_python_packages_directory" "$MARKERS_DIRECTORY"
    _prepare_staging_directory "$cortex_staging_directory"

    if ! pip install --no-cache-dir --target "$cortex_staging_directory" "numpy==2.4.4" "scipy==1.17.1"; then
        _abort_bake "Cortex NumPy/SciPy bake failed"
    fi

    if ! pip install --no-cache-dir --target "$cortex_staging_directory" --no-deps "xgboost==3.2.0"; then
        _abort_bake "Cortex XGBoost bake failed"
    fi

    _sync_staged_python_packages_to_image "CORTEX" "$cortex_staging_directory" "$cortex_python_packages_directory"
    _write_marker_ok "$CORTEX_PACK_NAME" "$CORTEX_PACK_VERSION"
    echo "[BAKE][OPTIONAL_DEPENDENCIES][CORTEX] Pack baked successfully"
}

_bake_chart_ai_vision_pack() {
    echo "[BAKE][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Baking pack version ${CHART_AI_VISION_PACK_VERSION}"
    chart_ai_vision_python_packages_directory="${PYTHON_PACKAGES_ROOT}/${CHART_AI_VISION_PACK_NAME}"
    chart_ai_vision_staging_directory="${OPTIONAL_DEPENDENCIES_BAKE_STAGING_ROOT}/${CHART_AI_VISION_PACK_NAME}"
    mkdir -p "$PLAYWRIGHT_BROWSERS_DIRECTORY" "$chart_ai_vision_python_packages_directory" "$MARKERS_DIRECTORY"
    _prepare_staging_directory "$chart_ai_vision_staging_directory"

    if ! pip install --no-cache-dir --target "$chart_ai_vision_staging_directory" -r /app/backend/requirements-chart-ai-vision.txt; then
        _abort_bake "Chart AI vision pip bake failed"
    fi

    _sync_staged_python_packages_to_image "CHART_AI_VISION" "$chart_ai_vision_staging_directory" "$chart_ai_vision_python_packages_directory"

    export PYTHONPATH="/app/backend:${chart_ai_vision_python_packages_directory}"
    export PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_DIRECTORY"

    echo "[BAKE][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Installing Chromium system dependencies"
    if ! python -m playwright install-deps chromium; then
        _abort_bake "Chart AI vision Playwright system dependency bake failed"
    fi

    if ! PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0 python -m playwright install chromium; then
        _abort_bake "Chart AI vision Playwright browser bake failed"
    fi

    _write_marker_ok "$CHART_AI_VISION_PACK_NAME" "$CHART_AI_VISION_PACK_VERSION"
    echo "[BAKE][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Pack baked successfully"
}

_write_runtime_environment_file() {
    pythonpath_segments="/app/backend:${PYTHON_PACKAGES_ROOT}/${CHART_AI_VISION_PACK_NAME}:${PYTHON_PACKAGES_ROOT}/${CORTEX_PACK_NAME}"
    {
        printf 'export PYTHONPATH="%s"\n' "$pythonpath_segments"
        printf 'export PLAYWRIGHT_BROWSERS_PATH="%s"\n' "$PLAYWRIGHT_BROWSERS_DIRECTORY"
    } > "$RUNTIME_ENVIRONMENT_FILE"
}

_bake_cortex_pack
_bake_chart_ai_vision_pack
_write_runtime_environment_file
chmod 644 "$RUNTIME_ENVIRONMENT_FILE"
touch "$POSEIDON_OPTIONAL_DEPENDENCIES_BAKED_MARKER"

echo "[BAKE][OPTIONAL_DEPENDENCIES] Optional dependencies baked successfully"
