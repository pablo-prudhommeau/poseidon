#!/bin/sh
set -eu

for writable_directory in \
    /app/backend/data/logs \
    /app/backend/data/models \
    /app/backend/data/memray \
    /app/backend/data/optional-dependencies/playwright-browsers \
    /app/backend/data/optional-dependencies/python-packages \
    /app/backend/data/optional-dependencies/markers \
    /app/data/screenshots \
    /app/db
do
    mkdir -p "$writable_directory"
    chown -R poseidon:poseidon "$writable_directory" 2>/dev/null || true
done

if [ -f /app/.poseidon-optional-dependencies-baked ]; then
    echo "[ENTRYPOINT] Optional dependencies baked image detected, skipping bootstrap"
else
    /app/deploy/bootstrap-optional-deps.sh
fi

exec /usr/bin/supervisord -c /etc/supervisord.conf
