#!/bin/sh
set -eu

if [ -f /app/backend/data/optional-dependencies/runtime-environment.sh ]; then
    . /app/backend/data/optional-dependencies/runtime-environment.sh
fi

exec python -m memray "$@"
