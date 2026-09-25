---
title: "Session 10 — Observability & Cost: Running It Like You Mean It"
session: 10
source: "oriolrius/esade-devops:backlog/docs/doc-12 - Session-10-Observability.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 10 — Observability & Cost: Running It Like You Mean It

Session 10 instruments the workbench that Session 09 exposed behind Traefik basic-auth: Prometheus and Grafana are installed on the student's k3s cluster via individual Helm charts, Qdrant's native `/metrics` endpoint is scraped through pod annotations, a blackbox HTTP probe watches the ingress from outside, and one alert rule plus an AWS Budget alert turn "the app feels slow" into an evidenced, gated operational fact. The end state is a student-built Grafana dashboard, a `WorkbenchDown` alert seen going `inactive → pending → firing` under an injected outage, and the student's own month-to-date AWS spend read from the CLI.

## The three pillars and the pull model

Metrics (numbers over time, Prometheus), logs (event text, `kubectl logs` today, Loki named as the future aggregation step), and traces (per-request call paths, not installed this session) are the three observability pillars — metrics tell you *that and how much*, logs tell you *why*. Prometheus is pull-based: it scrapes HTTP `/metrics` endpoints on an interval, and on Kubernetes it discovers targets through pod annotations `prometheus.io/scrape`, `prometheus.io/port`, `prometheus.io/path`. No annotation means no data and a flat dashboard even while the app works fine — this is the session's most common failure mode.

## Golden signals, white-box vs black-box, and metric types

The four golden signals from Google SRE are latency, traffic, errors, and saturation. Qdrant's own `/metrics` is white-box (the system telling you about itself); the blackbox HTTP probe of the workbench ingress is black-box (the user's-eye view from outside) — a healthy pod behind a broken ingress looks fine in white-box metrics only, which is exactly what the sabotage drill demonstrates. Three metric types matter: counters only go up (`rest_responses_total` — always wrap in `rate()` or `increase()`), gauges go up and down (`collections_vector_total` points stored, `probe_success`), and histograms bucket values for quantiles (`histogram_quantile(0.95, ...)`). An alert rule is an expression plus a `for:` duration that must stay true before firing, which prevents flapping; an AWS Budget alert only notifies, it never caps or stops spend — that discipline stays the student's job.

## Why individual Helm charts, not kube-prometheus-stack

The popular umbrella chart bundles the Prometheus Operator, CRDs, Alertmanager, and a fleet of exporters sized for multi-node production clusters — on one `t3.large` node it is memory-heavy and hides the exact mechanism the session teaches (how a scrape target is found). The lab installs Prometheus, Grafana, and the blackbox exporter as three separate Helm charts via `scripts/install-monitoring.sh` (from `starter-s10-v1.0.0`), with no Prometheus Operator and no CRDs. The classic AI-generated mistake is suggesting `kube-prometheus-stack` and a `ServiceMonitor` resource — on this cluster `ServiceMonitor` CRDs simply do not exist, so `kubectl apply` fails, or worse, students accidentally install the whole operator stack and OOM the node.

## Wiring Qdrant and the blackbox probe

Confirm the endpoint before configuring anything: Qdrant exposes native Prometheus metrics on port `6333` at `/metrics`, showing families like `collections_total`, `collections_vector_total`, `rest_responses_total`, and `rest_responses_avg_duration_seconds` — exact names must be read from the live `curl`, not assumed from a tutorial, because they shift across Qdrant versions. Scrape annotations go into the student's own `my-values.yaml` under `qdrant.podAnnotations`, then `helm upgrade workbench ./charts/ai-workbench -n workbench -f my-values.yaml`. Prometheus's Status → Targets page must show the Qdrant pod UP and the `workbench-probe` job UP. The blackbox probe authenticates with the same basic-auth credentials as the Session 09 ingress (Secret `workbench-probe-auth`, mounted read-only), using an `http` prober module with `basic_auth` username/password files; a 401 must fail the probe, and `probe_success` is 1 only when the application actually responds — `up` merely proves Prometheus reached the exporter.

## Building the dashboard and firing the alert

Five panels, each a golden-signal square: points stored (`sum(collections_vector_total)`), requests/min (`sum(rate(rest_responses_total[5m])) * 60`, traffic), response time (`rest_responses_avg_duration_seconds`, latency, white-box), pod CPU/memory (`container_cpu_usage_seconds_total` and `container_memory_working_set_bytes`, saturation), and workbench up plus probe latency (`probe_success` / `probe_duration_seconds`, errors and latency, black-box). Load is generated deterministically with `scripts/qdrant-load.py --seed` and `--queries 120` against a synthetic `monitoring_demo` collection — insertion moves the gauge, reads move the counter and duration gauge, and points can stay flat under query load. The `WorkbenchDown` rule (`probe_success{job="workbench-probe"} == 0`, `for: 2m`, severity `page`) is armed first, then the class scales `pi-web-ui` to zero replicas and watches the Prometheus Alerts page move `inactive → pending → firing` while Qdrant's white-box panels stay green — proof that black-box caught what white-box could not. Nothing pages anyone: Alertmanager notification routing is deliberately not installed.

## Cost: your key's spend and the AWS Budget

Token and spend visibility for the workbench lives entirely on the professor's central gateway's per-key view — the student's own Prometheus cannot graph it, because that gateway runs outside the student's cluster and Prometheus only sees what it scrapes. The student-side cost control is an AWS Budget (`Billing and Cost Management → Budgets`, monthly template, amount `$25`, alert at 80%), and `aws ce get-cost-and-usage` reads month-to-date spend from the laptop controller. The boardroom TCO table anchors this: a `t3.large` running 24/7 costs roughly $60/month versus ~$16/month stopped nights and weekends, plus ~$2.40/month for a 30 GB gp3 EBS volume and a $5/month course-gateway virtual key — the honest missing line item is the student's own operating time, which is exactly what managed observability products are priced to replace.

## Diagnosing common failures

If the scrape annotation is missing or points at the wrong port, the Targets page shows the target absent or down while the app itself answers chats fine — fix by inspecting pod annotations, correcting values, and re-running `helm upgrade`. If an AI-drafted PromQL query references a metric name that does not exist on the student's actual `/metrics` output (or proposes `litellm_*` metrics from a gateway that is not in this cluster), the panel stays empty; the mechanical fix is checking every metric name against a live `curl` before it goes in a panel.
