#!/bin/sh
# Build the SQLite DB from /app/data, then exec the bot.
# Idempotent: --reset wipes the existing DB first.
set -e

echo "[entrypoint] building DB at $DB_PATH from /app/data ..."
mkdir -p "$(dirname "$DB_PATH")"
python load.py --reset

echo "[entrypoint] DB built; starting: $*"
exec "$@"
