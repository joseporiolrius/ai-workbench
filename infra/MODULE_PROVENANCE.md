# S08 vendored module provenance

Source: `oriolrius/ec2-console`, `dbai/terraform/modules/workspace/`, revision
`b2a0b2a8f9b9620cfc2e9b41a14cf7b49202524f` (PR #43).
Provider: hashicorp/aws ~> 5.0, locked by `.terraform.lock.hcl`.

The S08 overlay adds only a `k3s_enabled` boolean and forwards it into the
bootstrap template. All other module files match the pinned source. The student
root opts into `user_data_replace_on_change` when k3s is enabled. This makes the
S08 first-boot transition replace the VM deliberately, preserving the separately
managed EIP. False preserves the earlier containers-profile adoption.

The S08 bootstrap template installs k3s v1.30.5+k3s1 and Helm v3.15.4.
Use `instance_type = "t3.large"`, `root_volume_gb = 30` and
`web_ingress_self = true` for operations-0.3.0.

Qualification: earlier-profile native plan unchanged; S08 plan replaces the VM
and EIP association without destroying the address allocation. A real apply
finished cloud-init successfully and non-sudo kubectl showed a Ready node.
The complete deployment/scaling/failed-rollout/rollback rehearsal also passed.

Change the shared module upstream first, then re-pin and re-vendor; keep this
explicit S08 template overlay documented.
