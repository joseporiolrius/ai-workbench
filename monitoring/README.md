# S10 monitoring — runbook

DNS/HTTPS diagnostics, expiry and renewal panels, shared-service ownership and
the bounded qualification procedure are in [DNS_TLS.md](DNS_TLS.md).

Three **independent** Helm releases in namespace `monitoring` watch the S9 workbench
(`workbench` namespace, pi-web-ui + Qdrant behind Traefik basic-auth):

| Release | Chart (pinned) | What it does |
|---|---|---|
| `prometheus` | prometheus-community/prometheus **29.33.0** (Prometheus v3.14.0) | scrapes kubelet/cAdvisor, node-exporter, kube-state-metrics, annotated pods (Qdrant) and the `workbench-probe` job; holds the `WorkbenchDown` rule; 7d retention on an 8Gi PVC |
| `blackbox` | prometheus-community/prometheus-blackbox-exporter **11.18.0** (v0.28.0) | module `workbench_authenticated`: calls the workbench URL **through Traefik with the basic-auth user** |
| `grafana` | grafana-community/grafana **13.2.5** (Grafana 13.2.2) | dashboards; datasource `http://prometheus-server.monitoring.svc.cluster.local`; 1Gi PVC |

Not installed, on purpose: Prometheus Operator / `ServiceMonitor` CRDs, Alertmanager (no
notification routing), Pushgateway, Loki. `kube-prometheus-stack` is **not** used.

Every chart version and image pin lives in [`../course-artifacts.yaml`](../course-artifacts.yaml).
All six images are `ghcr.io/oriolrius/*` mirrors pinned by tag **and** digest; the installer
refuses to run if any pin is missing or any rendered image is not one of them.

---

## 1. Probe credentials (do this first)

The probe uses the **same** user as your S9 ingress. One credential, three Secrets, always
written together by one script:

| Secret | Keys | Read by |
|---|---|---|
| `workbench/workbench-basic-auth` | `users` (bcrypt htpasswd) | Traefik (S9 ingress) |
| `monitoring/workbench-probe-auth` | `username`, `password` | blackbox, mounted read-only at `/etc/blackbox/auth/` |
| `monitoring/grafana-basic-auth` | `users` (same htpasswd) | Traefik, only for the homework Grafana route |

```bash
sudo apt-get install -y apache2-utils          # htpasswd, as in S9
./scripts/set-workbench-credentials.sh         # prompts: username, password (hidden, twice)
```

The script writes the values only into a `0700` temp dir (umask 077), passes them to
`kubectl` as files, and shreds the dir on exit. Nothing goes on a command line, into your
shell history, into Git or into the output. `monitoring/blackbox-values.yaml` contains **paths
only** (`username_file`/`password_file`).

**Rotation** = run the same script with the new password. Traefik switches immediately; the
probe follows when the kubelet refreshes the Secret volume (observed: ~60 s, during which
`probe_success` is 0 because the probe still sends the old password and gets a 401). The old
password then returns 401, the new one 200.

## 2. Install / repeat / recover

```bash
./scripts/install-monitoring.sh --dry-run     # prints the exact pinned helm commands; changes nothing
./scripts/install-monitoring.sh               # inventory gate -> preflight -> 3 x helm upgrade --install --wait -> readiness
```

- **Inventory gate** (`scripts/monitoring-inventory.py check`): pulls each chart at its pinned
  version, verifies the `.tgz` sha256, renders it with the committed values + pinned image
  overrides and checks **every** container and init container (subcharts included). An
  unpinned/unapproved image, a placeholder pin or a re-enabled optional workload
  (Alertmanager, Pushgateway, Grafana sidecar/init images …) fails **before** anything is installed.
- **Preflight**: fails with an explicit message if `monitoring/workbench-probe-auth` is
  missing or lacks `username`/`password` (it will not install a probe that can only report 0).
  The probe target is read from your workbench Ingress: `https://wb.aNNN.dbai24.i40sys.com/`.
  The installer rejects plaintext and unassigned URLs before sending credentials.
- **Repeat**: running it again converges to the same three `deployed` releases (only the
  revision numbers go up). The *first* repeat restarts the Grafana pod once (the chart re-quotes
  the preserved admin password, which changes a checksum annotation); the password and the
  PVC-backed dashboards are kept, and later repeats restart nothing.
- **Failure**: any failed Helm install/upgrade or unready workload exits nonzero
  (`ERROR: helm upgrade --install <release> failed`).
- **Recovery**: fix the cause (e.g. an image that could not be pulled) and run the installer
  again. A `failed` release is upgraded to a new `deployed` revision; nothing needs deleting.
  `MONITORING_TIMEOUT=10m` gives slow first pulls more time.

## 3. Verify

```bash
kubectl -n monitoring get pods                          # 5 pods Running
helm -n monitoring list                                 # prometheus, blackbox, grafana: deployed
python3 scripts/monitoring-inventory.py evidence        # pulled digests == pins, node platform
kubectl -n monitoring port-forward svc/prometheus-server 9090:80
#   laptop: ssh -i dbai.pem -L 9090:localhost:9090 ubuntu@<IP>  ->  http://localhost:9090
#   Status > Targets: workbench-probe UP; kubernetes-pods shows Qdrant once annotated (§5)
#   Graph: probe_success{job="workbench-probe"}  -> 1
```

## 4. Grafana — private access

```bash
kubectl -n monitoring port-forward svc/grafana 3000:80            # on the VM
ssh -i dbai.pem -L 3000:localhost:3000 ubuntu@<IP>                  # on the laptop -> http://localhost:3000
```

The Service is `ClusterIP`; there is no public Grafana port. User `admin`; the password is
generated by the chart into Secret `monitoring/grafana` and **kept across upgrades**. Read it
into your clipboard/password manager, never into a file you commit, a screenshot or your journal:

```bash
kubectl -n monitoring get secret grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Do not paste `helm get manifest grafana` or Secret YAML into evidence: both contain it (base64
is not encryption).

## 5. Make Prometheus find Qdrant

Qdrant serves Prometheus metrics natively on **6333 `/metrics`**. The course chart passes
`qdrant.podAnnotations` to the Qdrant pod (chart ≥ 0.2.0). In `my-values.yaml`:

```yaml
qdrant:
  podAnnotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "6333"
    prometheus.io/path: "/metrics"
```

```bash
helm upgrade workbench ./charts/ai-workbench -n workbench -f my-values.yaml --wait
```

The chart's `kubernetes-pods` job picks the pod up (observed UP within ~30 s). Symptoms of a
broken annotation (the app keeps answering: `/healthz` 200 in both cases):

| Fault | Targets page |
|---|---|
| port changed to `6334` (Qdrant's gRPC port) | Qdrant target **DOWN**, `net/http: HTTP/1.x transport connection broken` |
| annotation removed | Qdrant target **absent**; the dashboard goes flat |

> **Image note.** The course pins Qdrant **v1.15.5**. v1.15.0 (the S4–S8 Compose pin)
> panics on `GET /metrics` while its store is empty
> (`src/common/metrics.rs:92 … MetricFamily has no metrics: collection_hardware_metric_cpu`),
> so the target would show DOWN with `EOF`. Fixed upstream in 1.15.1. The S9 chart upgrade
> to 1.15.5 keeps the same PVC data (same storage format).

Cost (gateway spend vs AWS, Budgets, stop discipline): [COST.md](./COST.md).

See [METRICS.md](./METRICS.md) for every metric, its source and how to diagnose an empty panel.

## 6. Load: make each signal explainable

Three different kinds of traffic reach three different places. Label which one moved each panel.

| Workload | Command | Goes through | Moves | Does NOT move |
|---|---|---|---|---|
| **Synthetic Qdrant** | `uv run --project monitoring --locked python scripts/qdrant-load.py --seed` then `… --queries 120` (with `kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333`) | Qdrant REST only | `--seed`: points stored (gauge). `--queries`: Qdrant requests/min, avg response time, Qdrant CPU | pi-web-ui CPU, probe, gateway spend. Points stay flat under queries |
| **UI HTTP** | `./scripts/loadgen.sh -n 300 -c 4` | Traefik basic-auth → pi-web-ui (`GET /`, `/health`) | pi-web-ui CPU/memory, node CPU | Qdrant panels (0 Qdrant calls), gateway spend (0 chat, 0 tokens) |
| **Real chat** | type in the workbench UI | pi-web-ui → **professor's central gateway** | your key's spend on the gateway (projected by the professor) | Qdrant before S12 (no retrieval yet); nothing in your Prometheus shows tokens |

- `qdrant-load.py` only ever touches the collection `monitoring_demo` (500 deterministic 4-d
  points, seed 1010). It snapshots every other collection and alias (e.g. S12's `study_guides`)
  before and after and fails if any changed. `--cleanup` deletes only `monitoring_demo`.
  Unreachable Qdrant → exit 3 with a port-forward hint; missing demo collection → exit 1.
- `loadgen.sh` takes its credentials from `monitoring/workbench-probe-auth` into a shredded
  `0600` curl config. A preflight request must return 2xx or no load is sent (401 = wrong or
  rotated credential; 404 = backend scaled to zero, Traefik has no endpoint; 502/000 = backend
  dying/unreachable). During the run every non-2xx is counted as FAILED and makes the exit
  status nonzero. Bounds: `-n` ≤ 5000, `-c` ≤ 16.

**Reference observation** (qualified cluster, t3.large, 15 s scrape): seed → points 2 → 502;
1500 query pairs → ≈1959 Qdrant calls in the next minute, ≈357 req/min on the 5m panel, Qdrant
CPU ×8, pi-web-ui CPU unchanged; 3000 UI GETs (c=8) → pi-web-ui CPU 0.001 → 0.21 cores, node CPU
82 %, Qdrant calls 0/min, points flat; probe latency stayed ≈8 ms.

## 7. The alert: `WorkbenchDown`

```yaml
alert: WorkbenchDown
expr: probe_success{job="workbench-probe"} == 0
for: 2m
labels: { severity: page }
```

**No notification route exists** (no Alertmanager). `severity: page` is only a label: the
alert becomes `pending` and then `firing` on Prometheus's **Alerts** page and pages nobody.

Outage drill (qualified timings, 15 s scrape/evaluation):

```bash
kubectl -n workbench logs deploy/workbench-pi-web-ui -f --timestamps > /tmp/app.log &   # start BEFORE the break
kubectl -n workbench scale deploy/workbench-pi-web-ui --replicas=0
#   ~15 s: probe_success 1 -> 0 (Traefik 404, no endpoint); `up{job="workbench-probe"}` stays 1
#   next evaluation: WorkbenchDown pending (activeAt = first failing evaluation)
#   activeAt + 2m (+ one evaluation): firing
kubectl -n workbench scale deploy/workbench-pi-web-ui --replicas=1
#   ~25 s: probe_success -> 1; next evaluation: alert inactive
```

- An outage shorter than 2 minutes (≈60 s tested) goes `pending` and back to `inactive`; it never fires.
- While scaled to zero, `kubectl logs deploy/…` has **no pod to read** ("timed out waiting for
  the condition"). That's why the follow is started first: it captures the `shutting down…` line, and
  after restoration the new pod's startup banner (`bind : 0.0.0.0:8787`).
- `up{job="workbench-probe"}` = 1 only proves Prometheus reached the blackbox exporter. The
  application verdict is `probe_success`. A 401 (wrong/rotated probe credential) is also 0.

**Diagnosis:** blackbox tells you *why* a probe failed:

```bash
kubectl -n monitoring port-forward svc/blackbox-prometheus-blackbox-exporter 9115:9115
curl -s "localhost:9115/probe?module=workbench_authenticated&debug=true&target=http://wb.<IP>.sslip.io/" \
  | grep -E 'status_code|probe_success '
#   status_code=401 -> credential mismatch: re-run set-workbench-credentials.sh
#   status_code=404/502 -> backend down: kubectl -n workbench get pods; logs
```

## 8. Homework: Grafana behind your S9 basic-auth (you build it)

Write your own values file (e.g. `monitoring/grafana-route-values.yaml`) that layers on
`grafana-values.yaml`, then install with it and stop using the port-forward:

```bash
MONITORING_EXTRA_VALUES_GRAFANA=monitoring/grafana-route-values.yaml ./scripts/install-monitoring.sh
```

Facts you need (the rest is S9 knowledge):
- Host pattern: `grafana.<PUBLIC_IP>.sslip.io`, `ingressClassName: traefik`.
- A Traefik `Middleware` can only read a Secret **in its own namespace**, so it lives in
  `monitoring` and uses `monitoring/grafana-basic-auth` (the credentials script already keeps that
  copy of your S9 htpasswd in sync). The grafana chart can render extra objects: see its
  `extraObjects` value.
- Grafana has its own login. Make Traefik strip the Basic header after checking it
  (`removeHeader`), or Grafana will try to use it as a Grafana login.
- Prove it: no/wrong basic-auth → 401; with it → Grafana login page; after login your
  dashboard and datasource work, with every port-forward stopped. Rollback = install again
  without the variable.

Your extra values pass through the same inventory check, so they cannot add unpinned images.

## 9. Maintaining the pins (instructor)

1. Pick new chart versions; `helm pull` them and record `chart_version` + `chart_digest` (sha256 of the `.tgz`).
2. Render: `python3 scripts/monitoring-inventory.py check` lists every image. Mirror each one
   with `docker buildx imagetools create --tag ghcr.io/oriolrius/<name>:<tag> <upstream>`
   (digest-identical), make the GHCR package **public**, and record `image_ref`, `digest`,
   `upstream_*`, `platforms`.
3. Re-run `check` until PASS; keep optional workloads disabled rather than mirroring them. Never
   add the Operator, `ServiceMonitor`, Alertmanager routing, Pushgateway or Loki.
4. Requalify on a clean operations-profile cluster: install, `evidence`, probe 1→0→1, alert
   drill, memory (<≈80 % of 8 GiB; qualified: ≈25 % with workbench + monitoring under load).
   Then set the records back to `qualified` with new evidence.
