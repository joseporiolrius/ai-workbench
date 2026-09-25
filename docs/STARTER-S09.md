# S9 starter increment — `starter-s09-v1.0.0`

**Ref:** `starter-s09-v1.0.0` (annotated tag on the `starter-s09` lineage, a descendant of
`starter-s08-v1.1.0`). The tag is **immutable**: any fix is published as a new tag
(`starter-s09-v1.0.1`, `-v1.1.0` …), never by moving this one.

## Import (history already connected at S4)

```bash
git remote add upstream https://github.com/oriolrius/ai-workbench.git   # fresh clones only
git fetch upstream --tags
git merge starter-s09-v1.0.0 -m "chore: import S9 starter"
git push origin main
```

An ordinary merge: it **adds** files and never deletes or rewrites your `JOURNAL.md`,
`evidence/**`, `screenshots/**`, `my-values.yaml` (if you had started one), `infra/`, Compose
or `pi-config/`. Retained-file check (instructor): `esade-devops scripts/check-starter-inventory.py
--retained-check <repo> <before> <after>`.

## What this increment provides (instructor-owned)

| Path | What |
|---|---|
| `charts/ai-workbench/` | the course Helm chart **0.2.1**: pi-web-ui + Qdrant (2Gi local-path PVC), models ConfigMap, optional Ingress + Traefik basic-auth Middleware; `qdrant.podAnnotations` for S10. **Consumed, not authored.** |
| `scripts/with-release.sh` | runs a command inside a clean worktree at an **exact commit SHA** (`~/releases/workbench/<sha>`); rejects dirty trees; never touches your interactive checkout |
| `scripts/deploy.sh` | `helm upgrade --install workbench … -f my-values.yaml --atomic --wait` + a release receipt (SHA, chart, values hash, running images, readiness) |
| `scripts/RELEASE_WORKTREES.md` | how the two helpers fit together |
| `course-artifacts.yaml` | the tested inputs: UI images `ghcr.io/oriolrius/pi-web-ui:1.0.0` (label course-1.0.0) and `:1.1.0` (label course-1.1.0), Qdrant `ghcr.io/oriolrius/qdrant:v1.15.5`, gateway alias `course-chat` (nan.builders) — digests + evidence |

Input revisions this increment was qualified with: chart `0.2.0` (v1.0.0; v1.2.0 ships the 0.2.1 fix below); images as in
`course-artifacts.yaml`; ec2-console **operations** profile (`operations-0.2.0`: t3.large,
k3s v1.30.5+k3s1, kubectl v1.30.5, Helm v3.15.4); gateway `course-chat`.

## What YOU author in S9 (never shipped in a starter)

- `my-values.yaml`: your overrides (image, models provider, `existingKeysSecret`, Qdrant size,
  ingress host `wb.<PUBLIC_IP>.sslip.io` + basic-auth enable/secret name).
- `.github/workflows/deploy.yml`: your CD workflow (on `deploy-*` tags → SSH → `scripts/with-release.sh "$RELEASE_SHA" scripts/deploy.sh`).
- Cluster Secrets `workbench-keys` (your course virtual key) and `workbench-basic-auth`
  (your htpasswd), and the Actions secrets `VM_HOST` / `VM_SSH_KEY`: **never in Git**.
- The Terraform SG change that opens port 80, your journal and evidence.

Release discipline: commit workflow/helper changes and the **image-only** change
(`ui.image` 1.0.0 → 1.1.0) **separately**, so reverting the image never removes your workflow.

## v1.2.0 fix (2026-09-25)

Chart **0.2.1** renders `models.json` in the schema the pinned pi agent (0.85.1) actually reads,
`providers.course {baseUrl …/v1, api: openai-completions, apiKey: "$COURSE_VIRTUAL_KEY",
models: [course-chat]}`. It also mounts a writable `emptyDir` as the pi config dir, because pi
writes `auth.json` and `sessions/`, and it probes `/api/health`. Chart 0.2.0 rendered a
`{provider, baseUrl, model}` file that pi ignored, so the UI chat could not reply. Upgrading is
values-compatible: `helm upgrade workbench ./charts/ai-workbench -f my-values.yaml`.
Chat sessions live in the pod and do not survive a pod restart.
