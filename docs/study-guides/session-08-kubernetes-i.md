---
title: "Session 08 — Kubernetes I"
session: 08
source: "oriolrius/esade-devops:backlog/docs/doc-10 - Session-08-Kubernetes-I.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 08 — Kubernetes I

Session 08 moves hello-world from Docker Compose onto a self-healing, scalable Kubernetes
Deployment on a k3s cluster the student owns end to end. The same Terraform repo that provisioned
a `t3.medium` for Compose now provisions a `t3.large` whose cloud-init installs Docker and k3s;
the end state is every student personally scaling, killing, rolling-updating, and rolling back
their own pods on their own single-node cluster — there is no shared cluster, because breaking
things is the point.

## Rebuilding the machine: Terraform brings k3s

The lab begins by merging a course infra module update (`starter-s08-v1.1.0`) that introduces a
new `k3s_enabled` variable and a `t3.large` default instance type — this variable does not exist
in the module applied back in Session 6, so the merge must happen before editing tfvars. Setting
`instance_type = "t3.large"` and `k3s_enabled = true`, then running `terraform plan`, shows a
replacement (`-/+`) because the module uses `user_data_replace_on_change = true`: changed
cloud-init forces a fresh boot, so the VM is cattle, not a pet. The Elastic IP re-attaches
automatically to the new instance, so `VM_HOST` and the SSH target stay unchanged — the direct
payoff of Session 6's IaC discipline. After apply, the standard Session 6 recovery ritual repeats:
verify the new host's SSH fingerprint, restore GitHub access, re-clone both repos with upstream
remotes. The kubeconfig is world-readable (`--write-kubeconfig-mode 644`), so `kubectl` works
without sudo.

## The control loop: Kubernetes' core idea

Kubernetes controllers continuously compare desired state (declared in manifests, held by the API
server) against observed state and act to reconcile any difference — the thermostat model: you set
21°C, you do not personally operate the boiler. This is the same declarative principle as
Terraform in Session 6, now applied to a running system. `kubectl apply -f` is declarative and
converges the cluster to match the file; imperative commands like `kubectl scale` or
`kubectl set image` work immediately but create drift between the live cluster and the
version-controlled manifests — exactly like ClickOps drifted from Terraform.

## The three core objects: Pod, Deployment, Service

A Pod is the running unit — ephemeral, never created bare in production (the "bare-pod funeral":
a pod created with `kubectl run --restart=Never` that, once deleted, is gone forever, because
nothing wanted it back). A Deployment declares "N replicas of this pod template" and manages them
through ReplicaSets, enabling self-healing and rollback. A Service gives a stable name and port
that load-balances traffic across only the pods that are both selector-matched and currently
ready. In hello-world's manifests: `k8s/00-namespace.yaml` creates the `hello` namespace,
`k8s/10-deployment.yaml` declares 2 replicas with `imagePullSecrets` and both a readiness and
liveness probe on `GET /health`, and `k8s/20-service.yaml` is a NodePort Service (`port: 80`,
`targetPort: 8000`, `nodePort: 30080`) selecting `app: hello-world`. The Deployment's
`selector.matchLabels` must equal the pod template's labels — a mismatch is rejected outright by
the `apps/v1` API, a common AI-generated manifest bug.

## Liveness vs readiness probes

A failing liveness probe restarts the container; a failing readiness probe removes the pod from
the Service's endpoints without restarting it. Confusing the two turns a slow-starting application
into a crash loop (a liveness probe firing too early kills a pod that just needed more boot time).
In hello-world's manifests, `readinessProbe` uses `initialDelaySeconds: 3` and `livenessProbe`
uses `initialDelaySeconds: 10`, both hitting `GET /health` on port 8000.

## GHCR pull secrets: why the cluster needs its own credentials

Because the hello-world repo is a private copy, k3s's containerd runtime cannot pull images from
GHCR anonymously — and `docker login` performed on the same VM back in Session 5 does not help,
because dockerd and containerd do not share credentials. The cluster needs its own pull secret,
created once per namespace:

```bash
kubectl -n hello create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<PAT-with-read:packages>
```

The Deployment references it via `imagePullSecrets: [{ name: ghcr-pull }]`. Forgetting this secret
produces `ImagePullBackOff` even though the same image pulled fine under Compose.

## The drill: scale, kill, update, rollback

Four operations every student performs personally. Scaling
(`kubectl scale deployment/hello-world --replicas=4`) is imperative and immediately creates drift
against the manifest, which still says `replicas: 2`; re-running `kubectl apply -f
k8s/10-deployment.yaml` reconciles the cluster back to the file — declarative wins, the same lesson
as Terraform drift. Killing a pod owned by a Deployment (`kubectl delete pod <name>`) triggers
near-instant replacement because the ReplicaSet controller observes fewer running pods than
desired — the opposite outcome of deleting a bare pod, because a Deployment's desired state is
stored and enforced. A rolling update
(`kubectl set image deployment/hello-world app=ghcr.io/<you>/hello-world:v0.4.0`) creates a new
ReplicaSet and shifts pods gradually, readiness-gated, so the curl-loop against the Service never
errors. Breaking the rollout with a nonexistent tag (`v9.9.9`) produces `ImagePullBackOff` on new
pods while old, still-Ready pods keep serving — zero downtime — and
`kubectl rollout undo deployment/hello-world` restores the previous ReplicaSet revision, with
`kubectl rollout history` showing the revision list.

## Depth cap: what is explicitly out of scope

The session states an explicit depth cap: no Kustomize, no EKS or any managed control plane, no
operators, CRDs, RBAC internals, service meshes, or multi-node scheduling. Helm, Ingress,
ConfigMaps/Secrets, and PersistentVolumeClaims arrive in Session 9. If a student or their AI
assistant reaches for any of these during Session 8 — unsolicited Ingress, HPA, resource limits,
or Kustomize overlays in an AI-generated manifest — the correct response is to delete them:
today's manifests are course-supplied plain YAML on purpose, because the graded skill is operating
Kubernetes objects, not templating them.

## The boardroom angle: when is Kubernetes worth it

The Compose-vs-Kubernetes decision table (roughly $30/month for a single Compose VM versus
roughly $188/month for a managed Kubernetes baseline) frames the trade: Compose restarts a crashed
container on one machine but cannot load-balance, scale, drain, or roll back across machines.
Kubernetes is what an organization pays for — in money and complexity — once downtime and scale
cost more than an ops platform; a single large-scale outage can cost more than a year of the price
difference, and DORA elite performers deploy on demand precisely because rollback is a single
command. From this session on, the cost-discipline policy changes: rather than destroy-after-class,
students stop (never destroy) their instance, because k3s state lives on the node's local disk,
not in Terraform state.
