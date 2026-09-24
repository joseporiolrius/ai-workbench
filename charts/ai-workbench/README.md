# ai-workbench Helm chart (WB-06)

The S9 course chart for the persistent workbench. Students author **only**
`my-values.yaml` — never chart templates.

## Canonical names (release `workbench`, namespace `workbench`)

- Deployments/Services: `workbench-pi-web-ui`, `workbench-qdrant`
- ConfigMap `workbench-models-json` (mounted at `ui.configPath`)
- Qdrant PVC `workbench-qdrant` (local-path, `qdrant.persistence.size`, S9 baseline 2Gi)

## Configurable values (no template edits)

`ui.image`, `modelsJson` provider block, `existingKeysSecret`,
`qdrant.persistence`/pod settings, `ingress` (+`basicAuth`), and the
default-disabled `extension` interface. The UI reads `COURSE_VIRTUAL_KEY` from an
**existing** secret — the chart holds **no** real key and deploys **no** LLM
gateway.

## Persistence

Qdrant uses a `local-path` PVC; data survives pod replacement and chart upgrade.

## Boundary

This chart is the workbench only. Monitoring (Grafana/Prometheus) is a **separate**
chart (M07) — not shipped here.

```bash
helm lint charts/ai-workbench
helm template workbench charts/ai-workbench -n workbench
```
