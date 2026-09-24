# S10 metric handout — what you can graph, and where it comes from

Your Prometheus can only graph what it **scrapes**. Every series below was checked against the
pinned images on the qualified cluster. **Check the names against your own `/metrics`** before a
query goes into a panel, especially anything an AI assistant wrote.

| Metric | Type | Source (collection point) | Scrape job | Notes |
|---|---|---|---|---|
| `collections_vector_total` | gauge | Qdrant `:6333/metrics` (native) | `kubernetes-pods` (pod annotations) | points stored across all collections; rises on insert, flat under reads |
| `rest_responses_total{method,endpoint,status}` | **counter** | Qdrant `:6333/metrics` | `kubernetes-pods` | REST calls served. Always `rate()`/`increase()`. The series appears only after the first request |
| `rest_responses_avg_duration_seconds{method,endpoint,status}` | **gauge** (Qdrant's own average) | Qdrant `:6333/metrics` | `kubernetes-pods` | **never `rate()` it**. Use `max by (endpoint)` or filter `endpoint=~".*points/query.*"` |
| `container_cpu_usage_seconds_total{namespace,pod,container}` | counter | kubelet / cAdvisor | `kubernetes-nodes-cadvisor` | `rate(...[5m])` = cores. Filter `container!=""` to drop the pod-level aggregate series |
| `container_memory_working_set_bytes{namespace,pod,container}` | gauge | kubelet / cAdvisor | `kubernetes-nodes-cadvisor` | same `container!=""` filter |
| `node_cpu_seconds_total{mode}` | counter | node-exporter DaemonSet | `kubernetes-service-endpoints` | node CPU used = `1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))` |
| `node_memory_MemAvailable_bytes`, `node_memory_MemTotal_bytes` | gauge | node-exporter | `kubernetes-service-endpoints` | node headroom; what OOMs you |
| `kube_pod_container_status_restarts_total` | counter | kube-state-metrics | `kubernetes-service-endpoints` | restarts (exam extension alert) |
| `probe_success{job="workbench-probe"}` | gauge 0/1 | blackbox exporter, module `workbench_authenticated` | `workbench-probe` | 1 only if an **authenticated** request through Traefik got a 2xx from pi-web-ui |
| `probe_duration_seconds{job="workbench-probe"}` | gauge | blackbox exporter | `workbench-probe` | user's-eye latency (DNS + TCP + auth + app) |
| `up{job="..."}` | gauge 0/1 | Prometheus itself | every job | "Prometheus reached the target". For the probe job it means the exporter answered, **not** that the app is up |

What is **not** here, and why:

- **No gateway / LiteLLM / token metrics.** The LLM gateway is the professor's, outside your
  cluster. Your token spend lives in the gateway's per-key view. There is no `litellm_*`
  series to find.
- **No `ServiceMonitor`.** There is no Prometheus Operator, so the CRD does not exist. Discovery
  is by pod/service **annotations** (`prometheus.io/scrape|port|path`).

## Empty or missing series: diagnosis

1. **Is the name right?** Browse metric names in Grafana's metric browser or Prometheus's graph
   autocomplete. Names shift between versions; your query must match *your* `/metrics`.
2. **Is the target there and UP?** Prometheus → Status → Targets.
   - Qdrant **absent** → the pod has no `prometheus.io/scrape: "true"` annotation
     (`kubectl -n workbench get pod -l app=workbench-qdrant -o jsonpath='{.items[0].metadata.annotations}'`).
   - Qdrant **DOWN** → wrong port/path in the annotation, or Qdrant cannot serve `/metrics`
     (v1.15.0 with an empty store: `EOF`; the course pins v1.15.5). Test directly:
     `kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333 && curl -s localhost:6333/metrics | head`.
3. **Has the thing happened yet?** `rest_responses_*` only exists after the first REST call;
   `rate(x[5m])` needs two samples inside the window (15 s scrape → wait ≥30 s).
4. **Wrong label filter?** Drop filters until the series appears (e.g. `namespace="workbench"`
   vs your real namespace; `container!=""`).
5. **App fine but panel flat?** That is exactly the "annotation removed" fault. White-box
   metrics disappear while the black-box probe stays 1.
