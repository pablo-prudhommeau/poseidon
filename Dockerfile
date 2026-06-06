FROM python:3.11-slim AS slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    nginx \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements-core.txt /tmp/requirements-core.txt
RUN pip install --no-cache-dir -r /tmp/requirements-core.txt \
    && rm -f /tmp/requirements-core.txt

COPY alembic.ini /app/alembic.ini
COPY backend/ /app/backend/
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/supervisord.conf /etc/supervisord.conf
COPY deploy/optional-dependencies-pack-versions.sh /app/deploy/optional-dependencies-pack-versions.sh
COPY deploy/entrypoint.sh /app/deploy/entrypoint.sh
COPY deploy/bootstrap-optional-deps.sh /app/deploy/bootstrap-optional-deps.sh
COPY deploy/bake-optional-dependencies.sh /app/deploy/bake-optional-dependencies.sh
RUN sed -i 's/\r$//' \
    /app/deploy/optional-dependencies-pack-versions.sh \
    /app/deploy/entrypoint.sh \
    /app/deploy/bootstrap-optional-deps.sh \
    /app/deploy/bake-optional-dependencies.sh \
    && chmod +x /app/deploy/bootstrap-optional-deps.sh /app/deploy/bake-optional-dependencies.sh
COPY frontend/dist/frontend/browser/ /usr/share/nginx/html/

RUN groupadd --system poseidon \
    && useradd --system --gid poseidon --create-home --home-dir /home/poseidon poseidon \
    && mkdir -p \
        /app/backend/data/logs \
        /app/backend/data/models \
        /app/backend/data/memray \
        /app/backend/data/optional-dependencies/playwright-browsers \
        /app/backend/data/optional-dependencies/python-packages \
        /app/backend/data/optional-dependencies/markers \
        /app/data/screenshots \
        /app/db \
        /run/nginx \
    && rm -f /etc/nginx/sites-enabled/default \
    && chmod +x /app/deploy/entrypoint.sh \
    && chown -R poseidon:poseidon /app/backend /app/deploy /app/data /app/db /home/poseidon

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=5 CMD curl -fsS http://127.0.0.1/api/health || exit 1

ENTRYPOINT ["/app/deploy/entrypoint.sh"]


FROM slim AS full

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 CMD curl -fsS http://127.0.0.1/api/health || exit 1

RUN /app/deploy/bake-optional-dependencies.sh \
    && chown -R poseidon:poseidon /app/backend/data/optional-dependencies
