# Ingestion dependency image (S12)

`ghcr.io/oriolrius/workbench-ingestion` is the image the S12 candidate Job runs. The pinned digest
is recorded in [`course-artifacts.yaml`](../course-artifacts.yaml) (`id: image-workbench-ingestion`).

## What is inside, and what is not

| In the image | Mounted at run time from the release checkout |
|---|---|
| Python 3.12 and the virtual env `/opt/venv`, built from `ingestion/uv.lock` (httpx, PyYAML, pytest) | `ingestion/*.py`: the ingestion **source** |
| `/opt/deps/uv.lock.sha256`: the dependency identity baked into the image | `rag-settings.yaml`, `course-artifacts.yaml`, `docs/study-guides/*.md` |
| the entrypoint and a non-root user (uid 10001) | nothing secret: the key arrives through `secretKeyRef` |

The image contains no course source, settings or study guides. The Job mounts the exact
revision at `/workspace`, and the entrypoint runs `python ingestion/ingest.py` from there. A new
study guide, a settings change or an edit to `ingest.py` therefore reaches the Job **without a
rebuild**. The same digest ran three different bundles and produced three different candidates
(12 docs → 163 chunks, 13 docs → 164, `chunk_size 600` → 231).

## Failure modes (exit 2, before any write)

- `/workspace` is not mounted, or a required file is missing or unreadable, gives
  `mounted bundle is missing or unreadable: /workspace/<file>`.
- The mounted `ingestion/uv.lock` differs from the baked lock gives
  `… differs from this image's dependencies …: build and pin a new ingestion image`.

## When a new pin is required

Only when `ingestion/pyproject.toml` or `ingestion/uv.lock` change, which means the runtime
dependencies changed. The entrypoint enforces this: an old image refuses a bundle with a new
lock. To re-pin:

```bash
docker build --platform linux/amd64 -f ingestion/Dockerfile \
  --build-arg SOURCE_REVISION=$(git rev-parse HEAD) -t ghcr.io/oriolrius/workbench-ingestion:<next> .
docker push ghcr.io/oriolrius/workbench-ingestion:<next>
```

Then record the new digest in `course-artifacts.yaml`, repeat the bundle and VM smoke checks,
and use the new `image@sha256:…` in `k8s/ingest-job.yaml`. Source-only changes never need a new
image. Use the digest, never a tag alone.
