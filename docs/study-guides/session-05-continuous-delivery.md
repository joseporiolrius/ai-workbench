---
title: "Session 05 — Continuous Delivery"
session: 05
source: "oriolrius/esade-devops:backlog/docs/doc-7 - Session-05-Continuous-Delivery.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 05 — Continuous Delivery

Session 05 turns the CI pipeline built in earlier sessions into a full continuous delivery
pipeline: pushing a version tag builds the hello-world image, publishes it to GHCR, and
deploys it to the student's VM over SSH with zero manual steps. The end state is a two-command
release (`cz bump` + `git push --tags`) that takes a code change live, replacing the manual,
error-prone deploy measured back in Session 2.

## Continuous Delivery versus Continuous Integration

Continuous Integration answers "is it correct?" — tests run on every push. Continuous Delivery
answers "is it live?" — the release itself is performed by automation triggered by an event,
never by a person following a checklist. In hello-world, CI (`ci.yml`, from S3: ruff + pytest +
commit-message validation) remains untouched; a new workflow, `release.yml`, is added
specifically for delivery. The trigger for release is `on: push: tags: ["v*"]`, distinct from
CI's trigger on every push to main. A tag is treated as an explicit, versioned statement of
release intent, whereas ordinary pushes only validate correctness.

## Semantic versioning and commitizen

Versions follow MAJOR.MINOR.PATCH. Conventional commit prefixes drive the increment: `fix:`
implies PATCH, `feat:` implies MINOR, a `BREAKING CHANGE` footer implies MAJOR. The tool
`cz bump` (commitizen) reads the commit history since the last tag, picks the correct increment,
rewrites `version` in `pyproject.toml`, commits, and creates the git tag — so the version number
is derived from history, not invented by hand. Configuration lives in `pyproject.toml`:

```toml
[tool.commitizen]
name = "cz_conventional_commits"
version_provider = "pep621"
tag_format = "v$version"
```

Always dry-run first with `uv run cz bump --dry-run` to check the proposed increment matches
expectations before committing to a real bump. A real release is `uv run cz bump` followed by
`git push origin main --tags`.

## GHCR as the artifact registry

GHCR (GitHub Container Registry) stores versioned, immutable images at addresses of the form
`ghcr.io/<owner>/<image>:<tag>`, where owner must be lowercase (a common AI-generated mistake is
an uppercase GHCR path for capitalized usernames). A version tag such as `v1.3.0` is write-once
and immutable, enabling rollback; `latest` is a moving convenience pointer never used for
deployment selection. The deploy step always supplies the explicit release tag through the
environment variable `HELLO_IMAGE_TAG`. The build job authenticates to GHCR using the workflow's
automatic `GITHUB_TOKEN`, which requires `permissions: packages: write` declared at the top of
`release.yml` — omitting it produces a 403 on push that an AI assistant sometimes "fixes"
incorrectly with a personal PAT instead of the correct permissions block.

## Release pipeline shape and jobs

`release.yml` chains three jobs with `needs:`: `test` (ruff + pytest, same checks as CI) →
`build-push` (docker/build-push-action pushes the image to GHCR tagged with both
`${{ github.ref_name }}` and `latest`) → `deploy` (`appleboy/ssh-action` SSHes into the VM and
runs `docker compose pull && docker compose up -d`). The image is built exactly once, in CI —
immutable-artifact promotion: build once, run the same image everywhere. The classic AI-generated
failure mode is simplifying the deploy script to `docker compose up -d --build` on the VM, which
silently rebuilds the image on the server from whatever files are there, bypassing the registry
and breaking the guarantee that the artifact CI tested is the artifact in production.

## Secrets discipline and the deploy key

A dedicated SSH deploy key pair is generated on the laptop controller (never the personal key,
never generated inside the repo): `ssh-keygen -t ed25519 -f ~/.ssh/gha-deploy`. Its public half is
installed on the VM via `ssh-copy-id`; the private half is stored as the GitHub repository secret
`VM_SSH_KEY`, and the VM's stable Elastic IP is stored as `VM_HOST`. GitHub Secrets are encrypted
at rest, masked as `***` in workflow logs, and injected only at runtime — never committed, where
they would be readable forever via git history. A sanity check before releasing confirms the
private key never entered git history (`git log --all --oneline -- '*gha-deploy*'` returns
nothing).

## The VM side: compose.yml and the one-time GHCR login

On the VM, `~/hello-world/compose.yml` switches from the S4 locally-built image to the registry
image, parameterized by `HELLO_IMAGE_TAG`:

```yaml
services:
  hello-world:
    image: ghcr.io/<user>/hello-world:${HELLO_IMAGE_TAG:?set the release tag}
    ports: ["8000:8000"]
    restart: unless-stopped
```

This file must be committed to Git before deployment, since Session 6 restores the VM from Git.
The VM needs a one-time `docker login ghcr.io` using a classic PAT scoped only to
`read:packages` — this is the single manual credential the server needs before it can pull.
`docker compose pull` fetches the new image and `docker compose up -d` detects the changed image
reference via variable interpolation and recreates the container, even though the compose file
text itself did not change.

## The Release Ceremony and workbench pin verification

The lab culminates in a class-wide "Release Ceremony": every student makes a visible change (a
personalized greeting), then the whole class runs `cz bump` and `git push origin main --tags`
within the same ten-minute window, watching Actions run test → build-push → deploy and the new
greeting go live. Students measure their own lead time (wall-clock from push to new `curl`
output) and manual-step count (target: zero), re-measured against the Session 2 baseline —
directly exercising the two DORA metrics discussed in the boardroom segment (deployment
frequency and lead time for changes). Separately, students verify — not re-pin — that the
two-service workbench compose stack (pi-web-ui + Qdrant) still points at pinned GHCR tags rather
than `latest`, confirmed with `docker compose images`.

## DORA metrics and the boardroom angle

The four DORA metrics are deployment frequency, lead time for changes, change failure rate, and
time to restore; today's lab moves the first two. Elite teams deploy on demand, multiple times a
day, with lead time under one hour; low performers deploy less than once a month with lead times
of months — a 100x gap between equally-sized teams from pipeline maturity, not talent. The
business argument: when deploying is expensive and risky, teams batch changes into large, risky
releases; making deploys boring and automatic lets a company ship small, low-risk changes and
respond to the market faster.
