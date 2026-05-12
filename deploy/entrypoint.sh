#!/bin/sh
set -eu
exec /usr/bin/supervisord -c /etc/supervisord.conf
