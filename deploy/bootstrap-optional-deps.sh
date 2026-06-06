#!/bin/sh
set -eu

. /app/deploy/optional-dependencies-pack-versions.sh

OPTIONAL_DEPENDENCIES_ROOT="/app/backend/data/optional-dependencies"
PLAYWRIGHT_BROWSERS_DIRECTORY="${OPTIONAL_DEPENDENCIES_ROOT}/playwright-browsers"
PYTHON_PACKAGES_ROOT="${OPTIONAL_DEPENDENCIES_ROOT}/python-packages"
MARKERS_DIRECTORY="${OPTIONAL_DEPENDENCIES_ROOT}/markers"
RUNTIME_ENVIRONMENT_FILE="${OPTIONAL_DEPENDENCIES_ROOT}/runtime-environment.sh"

MEMRAY_PACK_NAME="memray"
MEMRAY_PACK_VERSION="memray-1.19.1"
BOOTSTRAP_STAGING_ROOT="/tmp/poseidon-bootstrap-staging"

_abort_bootstrap() {
    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][FATAL] $1" >&2
    exit 1
}

_as_bool() {
    normalized_value="$(printf '%s' "${1:-false}" | tr '[:upper:]' '[:lower:]')"
    case "$normalized_value" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

_is_pack_ready() {
    pack_name="$1"
    expected_version="$2"
    marker_file="${MARKERS_DIRECTORY}/${pack_name}.ok"
    if [ ! -f "$marker_file" ]; then
        return 1
    fi
    if [ "$(cat "$marker_file")" != "$expected_version" ]; then
        return 1
    fi
    return 0
}

_write_marker_ok() {
    pack_name="$1"
    version="$2"
    printf '%s' "$version" > "${MARKERS_DIRECTORY}/${pack_name}.ok"
    rm -f "${MARKERS_DIRECTORY}/${pack_name}.failed"
}

_write_marker_failed() {
    pack_name="$1"
    rm -f "${MARKERS_DIRECTORY}/${pack_name}.ok"
    touch "${MARKERS_DIRECTORY}/${pack_name}.failed"
}

_require_pack_ready() {
    pack_name="$1"
    expected_version="$2"
    if _is_pack_ready "$pack_name" "$expected_version"; then
        return 0
    fi
    _abort_bootstrap "Required optional dependency pack ${pack_name} is not ready after bootstrap"
}

_prepare_staging_directory() {
    staging_directory="$1"
    rm -rf "$staging_directory"
    mkdir -p "$staging_directory"
}

_sync_staged_python_packages_to_volume() {
    pack_label="$1"
    staging_directory="$2"
    target_directory="$3"

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][${pack_label}] Syncing staged Python packages to persistent volume (this can take a few minutes on slow disks)"
    mkdir -p "$target_directory"
    rm -rf "${target_directory:?}/"*
    cp -a "${staging_directory}/." "${target_directory}/"
    rm -rf "$staging_directory"
    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][${pack_label}] Persistent volume sync complete"
}

_configure_chart_ai_vision_runtime_environment() {
    chart_ai_vision_python_packages_directory="${PYTHON_PACKAGES_ROOT}/${CHART_AI_VISION_PACK_NAME}"
    export PYTHONPATH="/app/backend:${chart_ai_vision_python_packages_directory}${PYTHONPATH:+:${PYTHONPATH}}"
    export PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_DIRECTORY"
}

_install_chart_ai_vision_system_dependencies() {
    chart_ai_vision_python_packages_directory="${PYTHON_PACKAGES_ROOT}/${CHART_AI_VISION_PACK_NAME}"
    if [ ! -d "$chart_ai_vision_python_packages_directory" ]; then
        _abort_bootstrap "Chart AI vision Python packages directory is missing before system dependency install"
    fi

    _configure_chart_ai_vision_runtime_environment

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Installing Chromium system dependencies"
    if ! python -m playwright install-deps chromium; then
        _write_marker_failed "$CHART_AI_VISION_PACK_NAME"
        _abort_bootstrap "Chart AI vision Playwright system dependency install failed"
    fi
}

_install_chart_ai_vision_pack() {
    chart_ai_vision_python_packages_directory="${PYTHON_PACKAGES_ROOT}/${CHART_AI_VISION_PACK_NAME}"
    mkdir -p "$PLAYWRIGHT_BROWSERS_DIRECTORY" "$chart_ai_vision_python_packages_directory"

    if _is_pack_ready "$CHART_AI_VISION_PACK_NAME" "$CHART_AI_VISION_PACK_VERSION"; then
        echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Pack already installed with version ${CHART_AI_VISION_PACK_VERSION}"
        _install_chart_ai_vision_system_dependencies
        return 0
    fi

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Installing pack version ${CHART_AI_VISION_PACK_VERSION}"
    chart_ai_vision_staging_directory="${BOOTSTRAP_STAGING_ROOT}/${CHART_AI_VISION_PACK_NAME}"
    _prepare_staging_directory "$chart_ai_vision_staging_directory"

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Installing Python packages into container staging"
    if ! pip install --no-cache-dir --target "$chart_ai_vision_staging_directory" -r /app/backend/requirements-chart-ai-vision.txt; then
        _write_marker_failed "$CHART_AI_VISION_PACK_NAME"
        _abort_bootstrap "Chart AI vision pip install failed"
    fi

    _sync_staged_python_packages_to_volume "CHART_AI_VISION" "$chart_ai_vision_staging_directory" "$chart_ai_vision_python_packages_directory"

    _install_chart_ai_vision_system_dependencies

    if ! PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0 python -m playwright install chromium; then
        _write_marker_failed "$CHART_AI_VISION_PACK_NAME"
        _abort_bootstrap "Chart AI vision Playwright browser install failed"
    fi

    _write_marker_ok "$CHART_AI_VISION_PACK_NAME" "$CHART_AI_VISION_PACK_VERSION"
    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CHART_AI_VISION] Pack installed successfully"
}

_install_cortex_pack() {
    if _is_pack_ready "$CORTEX_PACK_NAME" "$CORTEX_PACK_VERSION"; then
        echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CORTEX] Pack already installed with version ${CORTEX_PACK_VERSION}"
        return 0
    fi

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CORTEX] Installing pack version ${CORTEX_PACK_VERSION}"
    cortex_python_packages_directory="${PYTHON_PACKAGES_ROOT}/${CORTEX_PACK_NAME}"
    cortex_staging_directory="${BOOTSTRAP_STAGING_ROOT}/${CORTEX_PACK_NAME}"
    mkdir -p "$cortex_python_packages_directory"
    _prepare_staging_directory "$cortex_staging_directory"

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CORTEX] Installing NumPy and SciPy into container staging"
    if ! pip install --no-cache-dir --target "$cortex_staging_directory" "numpy==2.4.4" "scipy==1.17.1"; then
        _write_marker_failed "$CORTEX_PACK_NAME"
        _abort_bootstrap "Cortex NumPy/SciPy install failed"
    fi

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CORTEX] Installing XGBoost into container staging (CPU-only, no CUDA dependencies)"
    if ! pip install --no-cache-dir --target "$cortex_staging_directory" --no-deps "xgboost==3.2.0"; then
        _write_marker_failed "$CORTEX_PACK_NAME"
        _abort_bootstrap "Cortex XGBoost install failed"
    fi

    _sync_staged_python_packages_to_volume "CORTEX" "$cortex_staging_directory" "$cortex_python_packages_directory"

    _write_marker_ok "$CORTEX_PACK_NAME" "$CORTEX_PACK_VERSION"
    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][CORTEX] Pack installed successfully"
}

_install_memray_pack() {
    if _is_pack_ready "$MEMRAY_PACK_NAME" "$MEMRAY_PACK_VERSION"; then
        echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][MEMRAY] Pack already installed with version ${MEMRAY_PACK_VERSION}"
        return 0
    fi

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][MEMRAY] Installing pack version ${MEMRAY_PACK_VERSION}"
    memray_python_packages_directory="${PYTHON_PACKAGES_ROOT}/${MEMRAY_PACK_NAME}"
    memray_staging_directory="${BOOTSTRAP_STAGING_ROOT}/${MEMRAY_PACK_NAME}"
    mkdir -p "$memray_python_packages_directory"
    _prepare_staging_directory "$memray_staging_directory"

    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][MEMRAY] Installing Python packages into container staging"
    if ! pip install --no-cache-dir --target "$memray_staging_directory" "memray==1.19.1"; then
        _write_marker_failed "$MEMRAY_PACK_NAME"
        _abort_bootstrap "Memray pip install failed"
    fi

    _sync_staged_python_packages_to_volume "MEMRAY" "$memray_staging_directory" "$memray_python_packages_directory"

    _write_marker_ok "$MEMRAY_PACK_NAME" "$MEMRAY_PACK_VERSION"
    echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES][MEMRAY] Pack installed successfully"
}

_write_runtime_environment_file() {
    pythonpath_segments="/app/backend"
    if [ -d "${PYTHON_PACKAGES_ROOT}/${CHART_AI_VISION_PACK_NAME}" ] && _is_pack_ready "$CHART_AI_VISION_PACK_NAME" "$CHART_AI_VISION_PACK_VERSION"; then
        pythonpath_segments="${pythonpath_segments}:${PYTHON_PACKAGES_ROOT}/${CHART_AI_VISION_PACK_NAME}"
    fi
    if [ -d "${PYTHON_PACKAGES_ROOT}/${CORTEX_PACK_NAME}" ] && _is_pack_ready "$CORTEX_PACK_NAME" "$CORTEX_PACK_VERSION"; then
        pythonpath_segments="${pythonpath_segments}:${PYTHON_PACKAGES_ROOT}/${CORTEX_PACK_NAME}"
    fi
    if [ -d "${PYTHON_PACKAGES_ROOT}/${MEMRAY_PACK_NAME}" ] && _is_pack_ready "$MEMRAY_PACK_NAME" "$MEMRAY_PACK_VERSION"; then
        pythonpath_segments="${pythonpath_segments}:${PYTHON_PACKAGES_ROOT}/${MEMRAY_PACK_NAME}"
    fi

    {
        printf 'export PYTHONPATH="%s"\n' "$pythonpath_segments"
        printf 'export PLAYWRIGHT_BROWSERS_PATH="%s"\n' "$PLAYWRIGHT_BROWSERS_DIRECTORY"
    } > "$RUNTIME_ENVIRONMENT_FILE"
}

mkdir -p \
    "$PLAYWRIGHT_BROWSERS_DIRECTORY" \
    "$PYTHON_PACKAGES_ROOT" \
    "$MARKERS_DIRECTORY"

if _as_bool "${TRADING_CHART_AI_VISION_ENABLED:-false}"; then
    _install_chart_ai_vision_pack
    _require_pack_ready "$CHART_AI_VISION_PACK_NAME" "$CHART_AI_VISION_PACK_VERSION"
fi

if _as_bool "${TRADING_GATE_CORTEX_ENABLED:-true}" || _as_bool "${TRADING_CORTEX_ENABLED:-false}"; then
    _install_cortex_pack
    _require_pack_ready "$CORTEX_PACK_NAME" "$CORTEX_PACK_VERSION"
fi

if _as_bool "${MEMRAY_ENABLED:-false}"; then
    _install_memray_pack
    _require_pack_ready "$MEMRAY_PACK_NAME" "$MEMRAY_PACK_VERSION"
fi

_write_runtime_environment_file
chmod 644 "$RUNTIME_ENVIRONMENT_FILE" 2>/dev/null || true

echo "[BOOTSTRAP][OPTIONAL_DEPENDENCIES] Runtime environment file written to ${RUNTIME_ENVIRONMENT_FILE}"
