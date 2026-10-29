# `infra/` — S6 Terraform adoption increment (RECOVERY-03)

In **S6** you adopt the controller's Terraform: instead of the dbai console
managing your workspace for you, you take ownership of a reviewable root that
drives the **same** resources. Adopting it is a **zero-change** plan — see
[EQUIVALENCE.md](./EQUIVALENCE.md).

## What's here

| File | Purpose |
|---|---|
| `main.tf` | terraform/provider/backend block + the `module "workspace"` block |
| `variables.tf` | non-secret inputs (mirror the module interface) |
| `outputs.tf` | `public_ip`, `instance_id` |
| `cloud-init.yaml` | bootstrap — **byte-identical** to the controller's containers profile |
| `terraform.tfvars.example` | non-secret inputs to copy (fill → `terraform.tfvars`, git-ignored) |
| `backend.hcl.example` | backend schema — the controller-owned local state path |
| `.terraform.lock.hcl` | pinned provider lock (`hashicorp/aws` 5.100.0) |
| `modules/workspace/` | vendored pinned shared module (see `MODULE_PROVENANCE.md`) |
| `EQUIVALENCE.md` | how to verify the zero-change adoption plan |
| `fixtures/expected-addresses.txt` | the resource addresses this root manages |

## Controller-owned vs. yours

- **Controller-owned, never committed:** the local backend **state**, AWS
  credentials, private keys, saved plans. These stay outside this repo
  (see `.gitignore`). You do not download the professor's state.
- **Yours, reviewable coursework:** this root, the vendored module, the
  non-secret inputs you copy, and — from earlier sessions — your app, Compose,
  config and journals. The S6 increment is **additive**; it changes none of them.

## Adopt (S6)

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill from EQUIVALENCE.md
terraform init -backend-config=path="$HOME/.local/state/ec2-console/dbai/<student_id>/workspace.tfstate"
terraform plan -detailed-exitcode              # expect: No changes (exit 0)
```

Only after a clean zero-change plan do you own the lifecycle (edit, then
`apply` / rebuild). `k3s_enabled` is **not** part of this pre-S8 interface.

## S08 bootstrap replacement

When `k3s_enabled = true`, the root enables `user_data_replace_on_change`.
Read the native plan before applying: this deliberately replaces the VM while
retaining its separately managed EIP. Use the operations-0.3.0 values
`t3.large`, 30 GB and `web_ingress_self = true`. Earlier-profile defaults retain
the zero-change adoption contract.
