# ---- Stage 1: build the SPA -------------------------------------------------
FROM node:20-slim AS client-build

WORKDIR /client

# Install JS deps from lockfile when available. `npm install` is the fallback
# for first-time builds before package-lock.json is committed.
COPY client/package.json client/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copy the rest of the SPA source and build.
COPY client/ ./
RUN npm run build
# Result: /client/dist/...


# ---- Stage 2: final Python image -------------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Layer caching: install deps before copying the rest of the source.
COPY pyproject.toml README.md ./
COPY core/    ./core/
COPY bot/     ./bot/
COPY web/     ./web/
COPY effects.py ./
RUN pip install --no-cache-dir .[web]

# Runtime files: schema, loader, CLI scripts (handy for `docker exec`), data.
COPY schema.sql load.py lookup.py roll.py ./
COPY data/ ./data/

# Built SPA assets from stage 1. CLIENT_DIST env (set in compose) points here.
COPY --from=client-build /client/dist /app/client_dist

# Entrypoint is a safety-net: build the DB only if it doesn't already exist.
# Deliberate ref-data refreshes are handled by the `rmr-init` compose service.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/db/rmfrp.db \
    CLIENT_DIST=/app/client_dist

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "bot"]
