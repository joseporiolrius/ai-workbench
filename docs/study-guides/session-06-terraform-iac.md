---
title: "Session 06 — Terraform IaC"
session: 06
source: "oriolrius/esade-devops:backlog/docs/doc-8 - Session-06-Terraform-IaC.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 06 — Terraform IaC

Session 06 replaces console-managed infrastructure with Terraform code the student owns: the
same VM, security group, and key pair used since Session 2 are destroyed and recreated from the
repository plus retained controller state, address, and credentials. The end state is a
measured, full recovery — proof that the environment lives in code, not in one person's memory
of what they clicked.

## Infrastructure as Code and the ClickOps problem

IaC means infrastructure is defined in versioned, reviewable files instead of built by hand in a
cloud console ("ClickOps"). ClickOps infrastructure is unrepeatable, unauditable, and
unrecoverable — "Dave set it up in 2019 and Dave left" is the boardroom framing for why every
company eventually has a server nobody dares touch. Terraform is declarative: HCL describes the
desired end state and the tool computes the steps to get there, unlike imperative approaches
(console clicks, ad hoc shell scripts) that list exact commands. Boardroom numbers: a forgotten
`t3.large` costs roughly $0.08–0.09/h (~$60/month) doing nothing; across 100+ students that is
thousands of dollars of pure waste, which is why tagging and destroy discipline are graded, not
optional.

## The Terraform loop and plan symbols

Four core commands: `terraform init` (downloads providers, once per repo), `terraform plan`
(computes the diff between code and known state, changes nothing), `terraform apply` (executes
the plan), and `terraform destroy` (removes everything the state manages). Plan output uses
symbols students must read cold: `+` create, `-` destroy, `~` update in place, `-/+`
destroy-and-recreate (replace). The course rule is explicit: nobody applies a plan they have not
read, and `-auto-approve` reflexes are flagged as a bad habit.

## State: what it is and why it is never committed

`terraform.tfstate` maps the HCL code to real AWS resource IDs — it is the only way Terraform
knows what it manages. It is never committed to git and never hand-edited: losing it does not
delete the underlying resources, but orphans them (they still exist, unmanaged). The provider
lock file, `.terraform.lock.hcl`, by contrast, is committed. Terraform and ec2-console run on the
laptop controller, outside the VM they manage; the controller keeps a separate address (Elastic
IP) state from the workspace (instance, security group, key) state, and workspace destroy cannot
release the address. State lives only in the controller's external state directory, never on the
disposable VM.

## Idempotency and cloud-init

Idempotency means applying the same configuration twice yields "No changes." — same input, same
end state — which is what makes IaC safe to re-run and enables drift detection. `cloud-init`
fills the gap between a blank VM and a configured one: it runs once, at first boot, and in this
course's cloud-init.yaml it installs Docker. Ansible is named as the classic tool for configuring
fleets of long-lived VMs, but the course deliberately keeps it a concept rather than a hands-on
lab — cloud-init plus containers cover that role here.

## Lab Block A: adopting ec2-console's existing Terraform

Students do not create infrastructure from scratch; they adopt the Terraform state that
ec2-console already manages for their VM (created back in Session 2). Key files live under
`infra/`: `main.tf` (pinned shared ec2-console workspace module), `variables.tf`,
`cloud-init.yaml`, `outputs.tf`, `terraform.tfvars` (nonsecret student inputs), and
`.terraform.lock.hcl`. After copying nonsecret values (region, `instance_type = "t3.medium"`,
`my_ip_cidr`, key paths, `eip_allocation_id`) into `terraform.tfvars`, students run:

```bash
terraform init -backend-config=<controller-backend-config>
terraform validate
terraform plan -detailed-exitcode
```

Exit code 0 means no changes (successful adoption); exit 1 is an error; exit 2 means the adopted
configuration does not match the original and must be resolved before proceeding. Students then
change one cost tag, save a plan file (`terraform plan -out=tfplan`), explain the diff to a
partner, and `terraform apply tfplan` — followed by a second plan confirming "no changes" again.
Students also preview (but do not apply) an `instance_type = "t3.large"` change, distinguishing
an in-place update from a destroy-and-recreate replacement — this upsize becomes real in
Session 8.

## Lab Block B: destroy and rebuild under a recovery timer

The capstone drill: students run `terraform destroy` from the workspace root (verifying the plan
does not touch `aws_eip`, since the address is separate state), start a recovery timer, then
`terraform apply` to rebuild. The retained Elastic IP re-associates automatically, so `VM_HOST`
never changes. Recovery requires: verifying the new host's SSH fingerprint through a trusted
channel (never blindly accepting — `StrictHostKeyChecking=accept-new` does not accept a *changed*
known key, so the stale known_hosts entry must be removed only after verification); restoring
outbound GitHub access and re-cloning both hello-world and ai-workbench with their upstream
remotes; re-authenticating Docker to GHCR; then proving recovery by cutting a new patch release
(`uv run cz bump --increment PATCH` + `git push origin main --tags`) that deploys through the
unchanged pipeline, and by restoring the workbench `.env` and Compose stack with a working gateway
chat round-trip. The timer stops only when both hello-world and the workbench answer.

## Cost tagging, sizing, and the destroy-after-class policy

`t3.medium` (2 vCPU/4 GB) is sufficient for the Compose-only stack through Session 7; Session 8
moves to `t3.large` because k3s plus Prometheus/Grafana need more headroom, delivered as a
one-line tfvars change — the point of IaC. Cost tags (e.g. `Owner`, `Course`,
`ManagedBy=terraform`) make spend attributable and orphaned resources findable.
Destroy-after-class applies through Sessions 6–7 practice; practical exams retain stopped state
until grading permits cleanup; from Session 8 the policy flips to stop-not-destroy because
cluster/PVC state lives on the node's disk, not in Terraform state.

## Common failure modes and diagnosis

Watch for three classic AI-generated Terraform mistakes: hardcoding an AMI ID from the wrong
region or an old Ubuntu codename instead of the `noble` 24.04 data-source filter; putting AWS
credentials directly in the `provider "aws"` block; and suggesting `terraform.tfstate` be
committed "so the team can share it." Any of these triggers an automatic oral check. Diagnostic
habits to know cold: security-group or SSH ingress problems show as an external curl timeout with
nothing wrong locally (contrast with a binding problem, visible via `ss`); a narrowed or removed
ingress rule shows up as a `-/+` or rule change in `terraform plan`, never in application logs.
