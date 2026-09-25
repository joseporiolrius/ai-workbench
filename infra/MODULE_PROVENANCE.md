# Vendored module provenance

`infra/modules/workspace/` is a **pinned, verbatim copy** of the shared course
workspace module (RECOVERY-01), so this student root is self-contained and
reviewable without fetching a private repository during `terraform init`.

| Field | Value |
|---|---|
| Source repo | `oriolrius/ec2-console` |
| Source path | `dbai/terraform/modules/workspace/` |
| Pinned revision | `e6bae45c63a9fd56f41e0b4c8b5a9c97a9cdb2bf` (main, PR #21; previously `78281ae`) |
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

**starter v1.3.0 re-vendor (operations-0.3.0).** The module gains `root_volume_gb`, `web_ingress_cidrs`
and `web_ingress_self`. Their defaults reproduce the earlier resources, so an environment built
before them still plans zero changes. A VM rebuilt at S8 with `operations-0.3.0` needs
`root_volume_gb = 30` and `web_ingress_self = true` in your `terraform.tfvars`. The only local
delta from the ec2-console module is still the S8 `k3s_enabled` template input.
