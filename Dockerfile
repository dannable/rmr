FROM python:3.12-slim

WORKDIR /app

# Layer caching: install deps before copying the rest of the source.
COPY pyproject.toml README.md ./
COPY core/    ./core/
COPY bot/     ./bot/
COPY effects.py ./
RUN pip install --no-cache-dir .

# Runtime files: schema, loader, CLI scripts (handy for `docker exec`), data.
COPY schema.sql load.py lookup.py roll.py ./
COPY data/ ./data/

# Entrypoint builds the DB on every container start, then execs the CMD.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/db/rmfrp.db

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "bot"]
