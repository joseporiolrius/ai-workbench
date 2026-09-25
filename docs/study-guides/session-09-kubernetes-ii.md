---
title: "Session 09 — Kubernetes II: Operating the Workbench"
session: 09
source: "oriolrius/esade-devops:backlog/docs/doc-11 - Session-09-Kubernetes-II.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 09 — Kubernetes II: Operating the Workbench

Session 09 moves the ai-workbench stack (pi-web-ui + Qdrant) off manual `docker compose pull && docker compose up -d` over SSH and onto a Helm release on the student's own k3s cluster, exposed through a Traefik ingress that is deliberately opened and then locked down with basic-auth. The end state is a workbench reachable at a public URL, private by design, redeployed and rolled back through a tag-triggered CD pipeline instead of SSH-and-pray.

## Helm: chart, release, values

A chart is a versioned package of Kubernetes templates plus defaults; a release is one installed instance of a chart in a cluster with a numbered revision history; a values file is the student's own configuration layered on top of the chart defaults. The one command to know cold is `helm upgrade --install <release> <chart> -f values.yaml` — it both installs and updates, and it is safe to re-run: running it twice with no changes creates a new revision but no pod restarts, because the rendered manifests are identical. The course chart lives at `charts/ai-workbench` in the `ai-workbench` repo, pulled from the `upstream` remote (`starter-s09-v1.0.0`). Never install a chart blind — `helm show values ./charts/ai-workbench` shows the configurable surface before touching `my-values.yaml`. Helm authoring/templating is explicitly out of scope this session; students consume charts, they do not write `{{ .Values }}` templates.

## ConfigMap, Secret, and PersistentVolumeClaim

Both ConfigMaps and Secrets inject configuration into pods as env vars or mounted files. ConfigMaps hold plain config — the workbench's `models.json` (rendered from `piWebUi.modelsJson` in `my-values.yaml`) pointing pi-web-ui at the professor's central course gateway. Secrets are the convention for sensitive values — the `COURSE_VIRTUAL_KEY`, created out-of-band with `kubectl create secret generic workbench-keys -n workbench --from-literal=COURSE_VIRTUAL_KEY=...` and referenced in values via `existingKeysSecret`, never committed to git. Secrets are base64-*encoded*, not encrypted — a Secret alone is not a vault. Separately, Qdrant needs a PersistentVolumeClaim because a pod's filesystem dies with the pod; a PVC (`qdrant.persistence.size: 2Gi` in values) requests durable storage from a StorageClass. On k3s the default `local-path` StorageClass stores data on the node's disk: durable across pod deletion and rescheduling, but not durable across loss of the node itself.

## The front door: Ingress, Traefik, and the basic-auth milestone

Nothing in the cluster is reachable from the internet until an Ingress routes a host/path to a Service; Traefik (already shipped inside k3s) executes those rules, and a Middleware — here `basicAuth` — processes every request before it reaches the app. This session's milestone is proving both halves: first expose the workbench at `wb.<PUBLIC_IP>.sslip.io` with `ingress.basicAuth.enabled: false` and confirm with `curl -i` that it returns **HTTP 200, no credentials asked** — a public shell, since pi-web-ui ships an unauthenticated terminal and a bash-running agent. Then create a bcrypt htpasswd credential (`htpasswd -nbB student ...`), store it as `kubectl create secret generic workbench-basic-auth --from-file=users=auth`, flip `basicAuth.enabled: true` with `secretName: workbench-basic-auth`, and re-run `helm upgrade --install`. The chart renders a Traefik `Middleware` (API `traefik.io/v1alpha1`) wired to the Ingress via the annotation `traefik.ingress.kubernetes.io/router.middlewares: workbench-workbench-auth@kubernetescrd`. Verification is mandatory evidence: an unauthenticated `curl -i` must now return `401 Unauthorized`, and `curl -i -u student:pass` must return `200 OK`. The classic AI-generated trap is answering "basic auth on Kubernetes ingress" with **nginx-ingress annotations**, which Traefik silently ignores — the site stays open while the student believes it's locked; the missing-namespace-prefix middleware name (`workbench-auth@kubernetescrd` instead of `workbench-workbench-auth@kubernetescrd`) is the same failure in disguise. The countermeasure is always the curl test itself, not reading the YAML.

## CD pipeline for the workbench, and retiring Compose

Lab C gives `ai-workbench` its **first** `.github/workflows/deploy.yml`, triggered on `push.tags: ["deploy-*"]`, using the `with-release.sh` / `deploy.sh` scaffolds (same SSH-transport pattern as hello-world's Session 5 pipeline, with its own `VM_HOST`/`VM_SSH_KEY` Actions secrets). `with-release.sh` creates a clean detached checkout at `~/releases/workbench/<SHA>` and never touches the student's interactive checkout or resets to main; `deploy.sh` runs `helm upgrade --install ... --atomic --wait --timeout 3m` against that checkout. The `--wait` flag matters: without it, `helm` returns as soon as objects are submitted, so a job can go green while pods crash-loop in `ImagePullBackOff` — `--wait` fails the job unless pods become Ready. After a tag-triggered rolling update, `helm rollback workbench -n workbench` restores a previous revision in seconds but leaves the cluster drifted from the repo; the durable fix is `git revert` flowing back through the pipeline with a new tag. Once the pipeline is proven, `docker compose down` retires the Compose runtime for good (files stay in git for history).

## Releases as transactions

Every `helm upgrade` records a numbered revision; `helm history <release>` lists them, and `helm rollback <release> <rev>` restores one instantly. This is the same idempotency contract as `terraform apply`. `helm get values workbench --revision N` is the tool for proving exactly what changed between two revisions during an oral spot-check.

## Boardroom angle: the economics of a public front door

Today's business lesson is that basic-auth plus private-by-default is nearly free insurance against a very expensive failure. Internet-wide scanners find new open port-80 endpoints within minutes; credential-stuffing bots hit every login form they see. Pricing a breach of an open pi-web-ui: crypto-mining charges on the AWS bill, a stolen `COURSE_VIRTUAL_KEY` burned on someone else's LLM traffic, the VM used as a pivot, plus incident-response hours. The counter-control costs one Secret and one Middleware — zero application code changes.

## Common failure modes to diagnose

An open door that looks locked (wrong ingress-controller annotation family or an unprefixed middleware name) is only caught by an unauthenticated curl returning something other than 401. A "green" deploy that shipped a broken pod is only caught by removing (or restoring) `--wait` and reading `kubectl describe pod` for `ImagePullBackOff`. Both patterns recur as practical exam fault injections in this session.
