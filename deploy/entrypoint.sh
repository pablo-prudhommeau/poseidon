#!/bin/sh
set -eu

for writable_directory in \
    /app/backend/data/models \
    /app/backend/data/memray \
    /app/data/screenshots \
    /app/db
do
    mkdir -p "$writable_directory"
    chown -R poseidon:poseidon "$writable_directory" 2>/dev/null || true
done

exec /usr/bin/supervisord -c /etc/supervisord.conf
