# syntax=docker/dockerfile:1.7

ARG NEXUS_RUNTIME_IMAGE
FROM ${NEXUS_RUNTIME_IMAGE} AS runtime-assets

FROM python:3.11-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

RUN python -m pip install --no-cache-dir uv==0.11.8
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY nexus_v2 ./nexus_v2
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.11-slim-bookworm AS runtime

ARG VCS_REF=unknown
ARG RUNTIME_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/lucapohl-angel/N.E.X.U.S-ML-V2" \
      org.opencontainers.image.revision="${VCS_REF}" \
      io.nexus.runtime.ref="${RUNTIME_REF}"

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXUS_PROJECT_ROOT=/app \
    NEXUS_REQUIRE_API_KEY=true \
    NEXUS_RUNTIME_ASSETS_ROOT=/runtime-assets \
    NEXUS_PERFORMANCE_PROFILE=auto

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 nexus \
    && useradd --uid 10001 --gid nexus --no-create-home --home-dir /nonexistent nexus

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=runtime-assets /runtime-assets /runtime-assets
COPY profiles ./profiles
RUN chmod -R a=rX /app/profiles /runtime-assets

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/v2/health',timeout=4)); raise SystemExit(0 if data.get('status')=='ok' and data.get('engine_loaded') and data.get('authentication_required') else 1)"]

CMD ["nexus-api", "--host", "0.0.0.0", "--port", "8000"]
