FROM node:24-alpine AS frontend-build

WORKDIR /app/frontend
ENV CI=1
RUN corepack enable

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build:prod


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl nginx supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir memray \
    && python -m playwright install --with-deps chromium \
    && rm -f /tmp/requirements.txt

COPY alembic.ini /app/alembic.ini
COPY backend/ /app/backend/
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/supervisord.conf /etc/supervisord.conf
COPY deploy/entrypoint.sh /app/deploy/entrypoint.sh
COPY --from=frontend-build /app/frontend/dist/frontend/browser/ /usr/share/nginx/html/

RUN groupadd --system poseidon \
    && useradd --system --gid poseidon --create-home --home-dir /home/poseidon poseidon \
    && mkdir -p /app/backend/data/models /app/backend/data/memray /app/data/screenshots /app/db /run/nginx \
    && rm -f /etc/nginx/sites-enabled/default \
    && chmod +x /app/deploy/entrypoint.sh \
    && chown -R poseidon:poseidon /app/backend /app/deploy /app/data /app/db /home/poseidon /ms-playwright

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1/api/health || exit 1

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
