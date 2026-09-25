# S12 starter increment — `starter-s12-v1.0.0`

**Ref:** `starter-s12-v1.0.0` (annotated tag, descendant of `starter-s10-v1.2.0`). Immutable:
fixes ship as a new tag, never by moving this one.

## Import

```bash
git fetch upstream --tags
git merge starter-s12-v1.0.0 -m "chore: import S12 starter"
git push origin main          # a push to main, NOT a deploy-* tag: nothing is released yet
```

An ordinary merge. It **adds** the retrieval corpus, ingestion, evaluator and release helpers,
and it **updates** three instructor files:
- the chart `charts/ai-workbench` 0.2.1 → 0.3.0 (the `search_docs` extension, default off);
- `scripts/deploy.sh` (receipt gate, alias promotion, smoke test, compensation);
- `course-artifacts.yaml` (records appended; nothing earlier changes).

Your `my-values.yaml`, `.github/workflows/deploy.yml`, `JOURNAL.md`, `evidence/**`, `infra/`,
Compose, `pi-config/` and S10 dashboard/homework files are untouched.
Retained-file check (instructor): `esade-devops scripts/check-starter-inventory.py --retained-check <repo> <before> <after>`.

The live corpus is never touched by the import. The Qdrant alias `study_guides` only changes
when you promote an evaluated candidate (manual mode) or a `deploy-*` release passes its gate.

## Provided (instructor-owned)

| Path | What |
|---|---|
| `docs/study-guides/session-01..12-*.md`, `docs/CORPUS.md` | the versioned corpus (12 guides, 163 chunks, corpus hash `8626868a…`) and its rules |
| `evals/golden_set.yaml`, `evals/test_retrieval.py`, `evals/conftest.py`, `evals/QUALIFICATION.md` | the ten professor questions, the hit@3 ≥ 0.8 gate, the qualification record |
| `ingestion/` (`ingest.py`, `search.py`, `rag.py`, `corpus.py`, tests, `pyproject.toml`, `uv.lock`, `.python-version`, `Dockerfile`, `entrypoint.sh`, `IMAGE.md`, `README.md`) | readable, locked ingestion/search; source of the pinned ingestion image |
| `rag-settings.yaml` | chunking and the **ingestion** alias (`course-embed`) |
| `k8s/ingest-job.yaml`, `scripts/ingest_bundle.py`, `scripts/run-ingestion.sh` | the exact-SHA candidate ingestion Job |
| `scripts/run-eval.sh`, `scripts/receipt.py` | evaluation + receipt bound to SHA/corpus/settings/image |
| `scripts/promote-corpus.sh`, `scripts/corpus_alias.py`, `scripts/production-lock.sh`, `scripts/recover-production.sh`, `scripts/qdrant-forward.sh` | atomic alias promotion/restore under one production lock |
| `scripts/deploy.sh` (updated), `scripts/smoke_release.py` | one recoverable release: receipt gate → Helm → alias → smoke (the agent must cite this SHA's corpus) |
| `charts/ai-workbench` 0.3.0 | adds `extensions.search_docs.{enabled,collection,topK}` (off by default) |
| `docs/RAG_RELEASE.md`, `docs/SEARCH_DOCS.md` | the runbook (§1–12) and the extension contract |
| `course-artifacts.yaml` | appends the ingestion image, `search_docs` extension and embedding-alias records plus the `retrieval:` contract |

Input revisions (qualified before this tag):
- ingestion image `ghcr.io/oriolrius/workbench-ingestion:0.1.0@sha256:9ffe55ae…` (amd64);
- `search_docs` extension `index.ts` sha256 `d9a9d838…` in chart 0.3.0;
- gateway aliases `course-chat` (nan.builders deepseek-v4-flash), `course-embed` and `course-embed-decoy` (nan.builders qwen3-embedding, 4096-d, `nan-split` route);
- GATEWAY-10 fixture results: good 10/10, decoy 2/10;
- Qdrant `v1.15.5`, pi-web-ui `1.0.0`, ec2-console `operations-0.2.0` (t3.large, k3s v1.30.5+k3s1).

## You author in S12 (never shipped)

- `extensions.search_docs.enabled: true` (and the `topK` homework) in **your** `my-values.yaml`.
- The `ingest → retrieval-eval → deploy` jobs in **your** `.github/workflows/deploy.yml`
  (RAG_RELEASE.md §10 gives the contract, not the file).
- Your five appended golden questions (`docs/CORPUS.md`, keep q01–q10).
- `docs/study-guides/session-13-defense-faq.md` in the stale-index drill (§12). The decoy
  `rag-settings.yaml` edit (§11) is reverted in a new commit.
- Evidence under `evidence/s12/` and your journal.
