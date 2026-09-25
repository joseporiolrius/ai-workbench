# Changelog

All notable changes to the DBAI **ai-workbench** course project are documented
here. This project adheres to [Semantic Versioning](https://semver.org/).

## [starter-s12-v1.0.0] — S12 retrieval and gated corpus release (STARTER-14)

### Added
- Corpus `docs/study-guides/` (12 guides) + `docs/CORPUS.md`; `evals/` golden set, gate and qualification.
- `ingestion/` locked project (ingest/search/rag/corpus + tests, image source), `rag-settings.yaml`.
- `k8s/ingest-job.yaml` and release helpers: `ingest_bundle.py`, `run-ingestion.sh`, `run-eval.sh`,
  `receipt.py`, `promote-corpus.sh`, `corpus_alias.py`, `production-lock.sh`,
  `recover-production.sh`, `qdrant-forward.sh`, `smoke_release.py`; runbook `docs/RAG_RELEASE.md`.
- `course-artifacts.yaml`: ingestion image, `search_docs` extension, embedding aliases, `retrieval:`.

### Changed
- Chart `ai-workbench` 0.2.1 → 0.3.0: `extensions.search_docs` (default off).
- `scripts/deploy.sh`: receipt gate + Helm + alias promotion + smoke test, with compensation.

## [starter v1.2.0] - 2026-09-25

### Fixed
- S9 chart **0.2.1**: `models.json` in pi's schema, a writable `emptyDir` pi config dir, and
  `/api/health` probes (chart 0.2.0's UI chat could not reply).
- `pi-config/models.json` now uses the schema of the pinned pi agent SDK (0.85.1):
  `providers.course {baseUrl, api: openai-completions, apiKey: "$COURSE_VIRTUAL_KEY",
  models: [course-chat]}`. The previous `providers: [...]` + `apiKeyEnv` form was
  silently ignored ("No models available"), so the UI chat could not work.
- `./pi-config` is mounted writable (pi writes `auth.json` and `sessions/`); runtime
  files are git-ignored.
- The pi-web-ui healthcheck probes `/api/health` (`/health` is the web app's fallback page).

## [0.1.0] - 2026-09-22

First tagged starter. Establishes the repository and the **S6 Terraform
adoption increment** (RECOVERY-03).

### Added
- `infra/` — the reviewable S6 student Terraform root that adopts the
  controller's workspace at the **same** shared module, provider config and
  resource addresses, so `terraform plan` against the controller-generated
  state is a **zero-change** plan (doc-18 §4).
  - `main.tf`, `variables.tf`, `outputs.tf` — `module "workspace"` wired
    identically to the ec2-console controller root.
  - `cloud-init.yaml` — **byte-identical** to the containers profile bootstrap
    template (`sha256 137bb7d5…`).
  - `modules/workspace/` — pinned shared module (RECOVERY-01) vendored verbatim
    from `oriolrius/ec2-console @ 78281ae`; `k3s_enabled` intentionally absent
    (pre-S8 interface).
  - `.terraform.lock.hcl` — pinned provider lock (`hashicorp/aws` 5.100.0).
  - `terraform.tfvars.example`, `backend.hcl.example` — non-secret inputs and
    backend schema to copy from the controller.
  - `EQUIVALENCE.md` + `fixtures/expected-addresses.txt` — the zero-change
    adoption check and the controller-generated values to copy, without a
    professor state download or a second state manager.
  - `MODULE_PROVENANCE.md` — vendored-module source, pinned revision and hash.
- `.gitignore` — excludes local backend state, credentials, private keys and
  saved plans from versioned coursework.

### Notes
- The S6 increment is **additive**: it does not modify app, Compose,
  `pi-config`, journals or evidence.
- This is the reviewable **scaffold**. The live zero-change adoption plan is the
  student's S6 acceptance action, documented in `infra/EQUIVALENCE.md`.
- The per-phase **immutable starter distribution** is published by the course
  starter tasks (M04); this repo holds the canonical content those starters are
  cut from. Earlier-session app/Compose history is added by later tasks.

[0.1.0]: https://github.com/oriolrius/ai-workbench/releases/tag/v0.1.0
