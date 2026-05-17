#!/bin/sh
# Safety-net entrypoint.
#
# - If the DB doesn't exist, build it from data/ (first-time bootstrap so the
#   container can come up even if rmr-init wasn't run).
# - If it does, leave it alone — user data lives here now, and deliberate
#   ref-data refreshes are done by the rmr-init compose service.
#
# Then exec the CMD (bot or web).
set -e

if [ ! -f "$DB_PATH" ]; then
    echo "[entrypoint] DB at $DB_PATH does not exist; initializing from data/"
    mkdir -p "$(dirname "$DB_PATH")"
    python load.py --reset
else
    echo "[entrypoint] DB exists at $DB_PATH; skipping init"
fi

echo "[entrypoint] starting: $*"
exec "$@"
