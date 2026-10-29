# ai-workbench Helm chart (WB-06)

The S9 course chart for the persistent workbench. Students author **only**
`my-values.yaml` — never chart templates.

## Canonical names (release `workbench`, namespace `workbench`)

- Deployments/Services: `workbench-pi-web-ui`, `workbench-qdrant`
- ConfigMap `workbench-models-json` (mounted as `models.json` inside the writable `emptyDir` pi config dir `ui.configDir`)
- Qdrant PVC `workbench-qdrant` (local-path, `qdrant.persistence.size`, S9 baseline 2Gi)

## Configurable values (no template edits)

`ui.image`, `modelsJson` provider block (rendered in pi's `providers` schema), `existingKeysSecret`,
`qdrant.persistence`/pod settings, `ingress` (+`basicAuth`), and the
default-disabled `extension` interface. The UI reads `COURSE_VIRTUAL_KEY` from an
**existing** secret — the chart holds **no** real key and deploys **no** LLM
gateway.

## DNS and HTTPS (0.3.0)

Public ingress requires your assigned `wb.aNNN.dbai24.i40sys.com` name and enabled
basic authentication. HTTP only redirects to HTTPS; HTTPS still returns401 without
credentials. The instructor provisions `ingress.tls.secretName` in the release's
namespace before class. The chart references that existing Secret and never creates
Certificate, Issuer, ACME account or TLS-key resources. Upgrades and rollbacks must
preserve the same hostname, authentication Secret and TLS Secret references.

Keep ingress disabled until prerequisites are ready. A legacy HTTP-only release
is rejected by the instructor's cluster admission guard; use a compatible qualified
tag for rollback. Do not remove that guard or authentication to make an old tag run.
Staging certificates are only for instructor qualification with explicit test CA
trust; they are not publicly trusted classroom certificates.

## Persistence

Qdrant uses a `local-path` PVC; data survives pod replacement and chart upgrade.

## Boundary

This chart is the workbench only. Monitoring (Grafana/Prometheus) is a **separate**
chart (M07) — not shipped here.

```bash
helm lint charts/ai-workbench
helm template workbench charts/ai-workbench -n workbench
```
