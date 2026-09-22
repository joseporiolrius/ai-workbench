# Vendored module provenance

`infra/modules/workspace/` is a **pinned, verbatim copy** of the shared course
workspace module (RECOVERY-01), so this student root is self-contained and
reviewable without fetching a private repository during `terraform init`.

| Field | Value |
|---|---|
| Source repo | `oriolrius/ec2-console` |
| Source path | `dbai/terraform/modules/workspace/` |
| Pinned revision | `78281ae5d438c6aa50b6aa542d4976f03c9b9772` (main) |
| Provider | `hashicorp/aws ~> 5.0` (locked to 5.100.0 in `.terraform.lock.hcl`) |

Because the module code and the `module "workspace"` block name match the
controller root exactly, every resource keeps the same address
(`module.workspace.aws_*`) — the basis for the zero-change adoption plan.

**Do not edit the vendored module here.** A module change is a course-wide
concern: it is made in `ec2-console`, re-pinned, and re-vendored. The
`k3s_enabled` input is intentionally absent from this pre-S8 interface.

`infra/cloud-init.yaml` is likewise byte-identical to the controller's
containers-profile bootstrap template
(`ec2-console dbai/profiles/containers/cloud-init.yaml.tftpl`):

    sha256(infra/cloud-init.yaml) = 137bb7d571dd0434ecb589a0d080a6e45b9f5a69efdb7425bb87a173d817829a
