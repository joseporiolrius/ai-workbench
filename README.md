# ai-workbench

DBAI course project workbench — the student's own repository that accumulates
coursework across the sessions: the application, its Docker/Compose and
`pi-config`, release workflow, journals and evidence.

> **Distribution:** the immutable per-phase starter history is published by the
> course starter tasks (M04). This repository holds the canonical content those
> starters are cut from.

## `infra/` — S6 Terraform adoption (RECOVERY-03)

[`infra/`](./infra/) is the S6 increment: a reviewable Terraform root that adopts
the controller's workspace at the **same** module, provider and resource
addresses, so adoption is a zero-change plan (doc-18 §4). It is **additive** —
it does not modify or remove the app, Compose, `pi-config`, journals or evidence
authored in earlier sessions, and it does **not** introduce the S8-only
`k3s_enabled`. See [`infra/README.md`](./infra/README.md) and
[`infra/EQUIVALENCE.md`](./infra/EQUIVALENCE.md).

Controller-owned state, credentials and private keys are never committed here
(see [`.gitignore`](./.gitignore)).

## S9 — Helm chart and CD helpers (`starter-s09-v1.0.0`)

`charts/ai-workbench/` (course chart, consumed), `scripts/with-release.sh` + `scripts/deploy.sh`
(exact-SHA release + atomic deploy with receipt) and `course-artifacts.yaml`. You author
`my-values.yaml` and `.github/workflows/deploy.yml`. See [`docs/STARTER-S09.md`](./docs/STARTER-S09.md).

## S10 — monitoring (`starter-s10-v1.0.0`)

Prometheus + blackbox exporter + Grafana as three pinned Helm releases, the authenticated
`workbench-probe`, the `WorkbenchDown` rule and synthetic load fixtures. You add the Qdrant
annotations, build and export the dashboard, and do the Grafana-route homework. See
[`docs/STARTER-S10.md`](./docs/STARTER-S10.md) and [`monitoring/README.md`](./monitoring/README.md).
