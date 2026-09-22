# Changelog

All notable changes to the DBAI **ai-workbench** course project are documented
here. This project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-22

First tagged starter. Establishes the repository and the **S6 Terraform
adoption increment** (RECOVERY-03).

### Added
- `infra/` — the reviewable S6 student Terraform root that adopts the
  controller's workspace at the **same** shared module, provider config and
  resource addresses, so `terraform plan` against the controller-generated
  state is a **zero-change** plan (doc-18 §4).
  - `main.tf`, `variables.tf`, `outputs.tf` — `module "workspace"` wired
    identically to the ec2-console controller root.
  - `cloud-init.yaml` — **byte-identical** to the containers profile bootstrap
    template (`sha256 137bb7d5…`).
  - `modules/workspace/` — pinned shared module (RECOVERY-01) vendored verbatim
    from `oriolrius/ec2-console @ 78281ae`; `k3s_enabled` intentionally absent
    (pre-S8 interface).
  - `.terraform.lock.hcl` — pinned provider lock (`hashicorp/aws` 5.100.0).
  - `terraform.tfvars.example`, `backend.hcl.example` — non-secret inputs and
    backend schema to copy from the controller.
  - `EQUIVALENCE.md` + `fixtures/expected-addresses.txt` — the zero-change
    adoption check and the controller-generated values to copy, without a
    professor state download or a second state manager.
  - `MODULE_PROVENANCE.md` — vendored-module source, pinned revision and hash.
- `.gitignore` — excludes local backend state, credentials, private keys and
  saved plans from versioned coursework.

### Notes
- The S6 increment is **additive**: it does not modify app, Compose,
  `pi-config`, journals or evidence.
- This is the reviewable **scaffold**. The live zero-change adoption plan is the
  student's S6 acceptance action, documented in `infra/EQUIVALENCE.md`.
- The per-phase **immutable starter distribution** is published by the course
  starter tasks (M04); this repo holds the canonical content those starters are
  cut from. Earlier-session app/Compose history is added by later tasks.

[0.1.0]: https://github.com/oriolrius/ai-workbench/releases/tag/v0.1.0
