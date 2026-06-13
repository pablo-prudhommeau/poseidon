#!/bin/sh
set -eu

MEMRAY_DIRECTORY="/app/backend/data/memray"
INPUT_PROFILE="${1:-${MEMRAY_DIRECTORY}/memory_profile.bin}"
OUTPUT_REPORT="${2:-${MEMRAY_DIRECTORY}/memory_profile.html}"
RUNTIME_ENVIRONMENT_FILE="/app/backend/data/optional-dependencies/runtime-environment.sh"

_restart_backend() {
    echo "[MEMRAY] Restarting backend..."
    supervisorctl start backend >/dev/null 2>&1 || true
}

if [ ! -f "$INPUT_PROFILE" ]; then
    echo "[MEMRAY] Capture file not found: ${INPUT_PROFILE}" >&2
    exit 1
fi

echo "[MEMRAY] Stopping backend to finalize the capture..."
supervisorctl stop backend

trap _restart_backend EXIT INT TERM

if [ -f "$RUNTIME_ENVIRONMENT_FILE" ]; then
    . "$RUNTIME_ENVIRONMENT_FILE"
fi

echo "[MEMRAY] Rendering flamegraph -> ${OUTPUT_REPORT}"
python -m memray flamegraph --force "$INPUT_PROFILE" -o "$OUTPUT_REPORT"

echo "[MEMRAY] Flamegraph ready: ${OUTPUT_REPORT}"
