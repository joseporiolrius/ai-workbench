# S10 starter increment — `starter-s10-v1.0.0`

**Ref:** `starter-s10-v1.0.0` (annotated tag, descendant of `starter-s09-v1.0.0`). Immutable:
fixes ship as a new tag, never by moving this one.

## Import

```bash
git fetch upstream --tags
git merge starter-s10-v1.0.0 -m "chore: import S10 starter"
git push origin main
```

An ordinary merge that only **adds** monitoring files. Your `my-values.yaml`,
`.github/workflows/deploy.yml`, `JOURNAL.md`, `evidence/**`, `infra/`, chart, Compose and
`pi-config/` are untouched. Retained-file check (instructor): `esade-devops
scripts/check-starter-inventory.py --retained-check <repo> <before> <after>`.

## Provided (instructor-owned)

| Path | What |
|---|---|
| `monitoring/prometheus-values.yaml` | Prometheus (7d, 8Gi PVC, 15s scrape, node-exporter, kube-state-metrics, cAdvisor), the `workbench-probe` job and the **`WorkbenchDown`** rule (`probe_success == 0` for 2m, severity `page`; no Alertmanager) |
| `monitoring/blackbox-values.yaml` | module `workbench_authenticated` (basic-auth **file paths** only) |
| `monitoring/grafana-values.yaml` | Grafana, datasource `prometheus-server.monitoring.svc.cluster.local`, 1Gi PVC, ClusterIP only |
| `scripts/install-monitoring.sh` + `scripts/monitoring-inventory.py` | pinned, idempotent install with an inventory gate + probe-Secret preflight |
| `scripts/set-workbench-credentials.sh` | one credential → ingress htpasswd + probe files (+ Grafana copy), never logged |
| `scripts/qdrant-load.py` + `monitoring/pyproject.toml` + `monitoring/uv.lock` | synthetic `monitoring_demo` workload (no embeddings, no key) |
| `scripts/loadgen.sh` | bounded authenticated UI load |
| `monitoring/README.md`, `METRICS.md`, `DASHBOARD_HANDOUT.md`, `COST.md` | runbook, metric handout, dashboard recipes, cost |
| `course-artifacts.yaml` | adds the `monitoring:` section + chart/image records to the S9 manifest |

Input revisions: charts prometheus-community/prometheus 29.33.0, prometheus-blackbox-exporter
11.18.0, grafana-community/grafana 13.2.5; six digest-pinned `ghcr.io/oriolrius` mirrors (see
`course-artifacts.yaml`); workbench chart 0.2.0 (from S9, Qdrant v1.15.5); ec2-console
`operations-0.2.0`; gateway `course-chat` (nan.builders).

## You author in S10 (never shipped)

- The Qdrant scrape annotations in **your** `my-values.yaml` (`qdrant.podAnnotations`).
- Your dashboard, exported to `monitoring/dashboards/workbench.json`.
- The homework Grafana route values (README §8) and the node-saturation panel.
- Evidence under `evidence/s10/` (exact names in `monitoring/DASHBOARD_HANDOUT.md`) and your journal.
