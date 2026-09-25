# S12 ingestion DEPENDENCY image (GATEWAY-09). It contains only the locked Python runtime
# dependencies of ingestion/. The course source, rag-settings.yaml and the study guides are
# NOT in the image: the candidate Job mounts the exact release checkout at /workspace from a
# revision-named ConfigMap, so a new study guide never needs a rebuild. Build from the repo root:
#   docker build -f ingestion/Dockerfile --build-arg SOURCE_REVISION=$(git rev-parse HEAD) .
FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv

FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
ARG SOURCE_REVISION=unknown
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 \
    PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/deps
COPY ingestion/pyproject.toml ingestion/uv.lock ingestion/.python-version ./
RUN uv sync --locked --no-install-project --python /usr/local/bin/python3.12 \
 && sha256sum uv.lock | cut -d' ' -f1 > /opt/deps/uv.lock.sha256 \
 && rm /usr/local/bin/uv \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin ingest
COPY ingestion/entrypoint.sh /usr/local/bin/ingest-entrypoint
USER 10001
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/ingest-entrypoint"]
LABEL org.opencontainers.image.source="https://github.com/oriolrius/ai-workbench" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="workbench-ingestion" \
      org.opencontainers.image.description="Dependency-only runtime for S12 ingestion: executes the mounted /workspace bundle (ingestion/*.py, rag-settings.yaml, docs). Rebuild and re-pin only when ingestion/pyproject.toml or uv.lock change."
