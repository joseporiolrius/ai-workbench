# Workspace module (RECOVERY-01)

The shared, pinned course workspace module. **Both** the initial controller root
(`dbai/terraform/workspace`) and the student S6 `ai-workbench/infra/` root
consume this module at one pinned revision with identical resource addresses, so
S6 adoption changes the editable root path — **not** resource identity
(doc-18 §4). A zero-change plan is the S6 acceptance check.

## Supported version

Terraform **≥ 1.9**, AWS provider **~> 5.0**. Consuming roots commit their
`.terraform.lock.hcl`. `k3s_enabled` is intentionally **absent** from this
pre-S8 interface; it is introduced only at the S8 boundary.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `student_id` | yes | environment identity; used in names/tags |
| `aws_region` | yes | region for the workspace |
| `my_ip_cidr` | yes | validated CIDR |
| `ssh_public_key_path` | yes | controller-local login public key (must exist) |
| `deploy_public_key_path` | no | S5 deploy public key; `null` until enrolled in S5 |
| `instructor_public_key_path` | no | instructor public key; `null` until required at S6 |
| `eip_allocation_id` | yes | `eipalloc-*` from the address state; **consumed, not owned** |
| `bootstrap_template_path` | yes | cloud-init template, used byte-identically |
| `instance_type` | yes | from the phase profile |
| `app_ingress_cidrs` | no | explicit CIDRs for application ports (default: none) |
| `cost_tags` | no | extra tags merged onto every resource |

Invalid or missing required inputs fail clearly via variable validation
(non-CIDR `my_ip_cidr`, missing key/template paths, non-`eipalloc-` id).

## Outputs

`public_ip` (the associated persistent EIP — the course-contract address),
`instance_id`, `vpc_id`, `security_group_id`, `ami_id`.

## Resources it owns

Network (`aws_vpc`, `aws_subnet`, `aws_internet_gateway`, `aws_route_table`
+ association), firewall (`aws_security_group`), key (`aws_key_pair`), VM
(`aws_instance`), and `aws_eip_association`. It **owns no `aws_eip`** — the
Elastic IP lives in the independent address state and is only consumed here, so
a workspace destroy can never destroy the address.

## Firewall

SSH (22) is key-only and open to `0.0.0.0/0` so hosted CI runners can reach the
VM. Application ports (8888–8889) open **only** to the explicit
`app_ingress_cidrs` — never an implicit `0.0.0.0/0`.

## AMI

The Ubuntu 24.04 LTS AMI is resolved by a `data "aws_ami"` filter for the
selected region (Canonical owner `099720109477`), avoiding wrong-region or
stale AMIs. No credentials are embedded in the provider configuration — they
come from the controller's temporary session.

## Verify

```bash
terraform -chdir=dbai/terraform/modules/workspace init -backend=false
terraform -chdir=dbai/terraform/modules/workspace validate
# plan a consuming root (interface + EIP separation + stable module.workspace.* addresses)
```
