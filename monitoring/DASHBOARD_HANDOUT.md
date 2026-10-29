# S10 dashboard handout — you build it

You build the **Workbench** dashboard yourself in Grafana. This handout gives the recipes and the
checks, not a finished dashboard. Confirm every metric name in [METRICS.md](./METRICS.md)
against your own `/metrics` first.

## Panels (one bingo square each)

For each panel: **Dashboards → New → Add visualization → datasource `Prometheus` → Code**,
paste the query, set the title and unit, **Apply**.

| # | Title | Query (starting point; adjust to your names) | Unit | Golden signal |
|---|---|---|---|---|
| 1 | Points stored in Qdrant | `sum(collections_vector_total)` | short | — |
| 2 | Qdrant requests/min | `sum(rate(rest_responses_total[5m])) * 60` | short | Traffic |
| 3 | Qdrant response time (avg, s) | `rest_responses_avg_duration_seconds` (then narrow it: which endpoint do you care about?) | seconds | Latency (white-box) |
| 4 | Pod CPU / memory | `sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="workbench"}[5m]))` and `container_memory_working_set_bytes{namespace="workbench"}` (why do you see a series with an empty `container`?) | cores / bytes | Saturation |
| 5 | Workbench up + probe latency | `probe_success{job="workbench-probe"}` and `probe_duration_seconds{job="workbench-probe"}` | — / seconds | Errors + latency (black-box) |

Save it as **Workbench**.

Add certificate days-remaining and readiness panels using the queries in
[DNS_TLS.md](DNS_TLS.md). A healthy HTTPS probe validates the assigned hostname,
certificate chain and basic-auth; `up` alone is only exporter availability.

## Checks before you call a panel done

- It shows data (not "No data") over the last 15 minutes.
- Counters are inside `rate()`/`increase()`; the average-duration **gauge** is not.
- You can say which workload moves it (see the load table in [README.md §6](./README.md)):
  `qdrant-load.py --seed`, `qdrant-load.py --queries N`, `loadgen.sh`, or a real chat.

## Evidence (commit exactly these paths)

| File | Shows |
|---|---|
| `evidence/s10/01-targets-up.png` | Prometheus Targets: the Qdrant pod and `workbench-probe` UP |
| `evidence/s10/02-dashboard-under-load.png` | your dashboard during the LOAD FEST, each panel labeled with the workload that moved it |
| `evidence/s10/03-workbench-down-firing.png` | `WorkbenchDown` firing on the Alerts page |
| `evidence/s10/04-cost.png` | the month-to-date AWS figure (projected by the professor in the sandbox) + your gateway spend row |
| `monitoring/dashboards/workbench.json` | your exported dashboard (homework) |
| `JOURNAL.md` | S10 entry: AI mistakes caught, how you verified, your gateway spend + timestamp |

No passwords, tokens or keys in any screenshot or file.

## Homework

1. Add a **node saturation** panel next to the per-pod one: node CPU used and node memory used
   from node-exporter (`node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`,
   `node_memory_MemTotal_bytes`). Compare node headroom with the pods' usage.
2. **Export** the dashboard (Share → Export → Save to file) and commit it as
   `monitoring/dashboards/workbench.json`. Check it contains no credentials.
3. Keep Grafana private through SSH/port-forwarding. Public HTTPS is optional and
   requires the instructor's separate hostname/certificate allocation; see README §8.
