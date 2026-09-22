# S6 adoption equivalence check

Adopting this root must be a **zero-change** operation: it drives the SAME
resources the controller already created, so `terraform plan` reports **no
changes**. You do this against the state the controller already made — you never
download the professor's state and never stand up a second state manager.

## What the controller already generated (copy these NON-SECRET values)

The dbai console created your environment and its state. From it, copy into
`terraform.tfvars` (git-ignored):

| Value | Where it comes from | Used for |
|---|---|---|
| `student_id` | your environment id | resource names/tags/`Environment` |
| `aws_region` | `environment.json` → `aws_region` (e.g. `eu-west-1`) | provider region |
| `eip_allocation_id` | `environment.json` → `eip_allocation_id` (`eipalloc-…`) | consumed EIP |
| `ssh_public_key_path` | your controller-local SSH public key | login enrollment |
| `instance_type` | containers profile → `t3.medium` (default; leave unset) | VM size |

Backend (state path), from the controller — never committed here:

    terraform -chdir=infra init \
      -backend-config=path="$HOME/.local/state/ec2-console/dbai/<student_id>/workspace.tfstate"

(or copy `backend.hcl.example` → `backend.hcl` and `init -backend-config=backend.hcl`.)

`bootstrap_template_path` defaults to `./cloud-init.yaml`, which is **byte-identical**
to the controller's containers-profile template (same sha256), so the rendered
user-data matches and no instance replacement is planned.

## Verify (the zero-change fixture)

```bash
cd infra
terraform init -backend-config=path="$HOME/.local/state/ec2-console/dbai/<student_id>/workspace.tfstate"
terraform plan -detailed-exitcode
#   exit 0  => No changes. Adoption is equivalent.  <-- PASS
#   exit 2  => a diff exists; DO NOT apply. Reconcile the copied inputs first.
```

The set of resource addresses this root manages is pinned in
[`fixtures/expected-addresses.txt`](./fixtures/expected-addresses.txt); it is
exactly the controller root's `module.workspace.*` address set. A plan that adds,
destroys or replaces any of them means an input was copied wrong — not that the
environment should change.
