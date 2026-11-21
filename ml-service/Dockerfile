# Pinned Python + uv base; update deliberately when refreshing dependencies.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim@sha256:4f5d923c9dcea037f57bda425dd209f3ec643da2f0b74227f68d09dab0b3bb36 AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/data/models
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /app /data/models /data/media && chown -R app:app /app /data
WORKDIR /app
COPY --chown=app:app pyproject.toml uv.lock ./
USER app

FROM base AS runtime
# Cache the heavy CPU dependencies independently of source changes. Do not retain
# a second copy of downloaded wheels in the image's uv cache.
RUN uv sync --no-cache --locked --no-dev --no-install-project
COPY --chown=app:app src ./src
COPY --from=migrations --chown=app:app V3*.sql ./migrations/
RUN uv sync --no-cache --locked --no-dev --no-editable
EXPOSE 8000
CMD ["uvicorn", "mediamesh_ml.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS tools
# Reuse the exact runtime/dependency layers; add only development dependencies.
RUN uv sync --no-cache --locked --no-editable
COPY --chown=app:app tests ./tests
COPY --chown=app:app evaluation ./evaluation
COPY --chown=app:app dev ./dev
CMD ["pytest"]
