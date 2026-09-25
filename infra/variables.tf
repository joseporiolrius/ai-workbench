# Inputs for the S6 student workspace root. All values are NON-SECRET and
# reviewable; the actual per-environment values are copied from the controller
# (see EQUIVALENCE.md) into terraform.tfvars, which is git-ignored.

variable "aws_region" {
  description = "AWS region for the course environment."
  type        = string
  default     = "eu-west-1"
}

variable "student_id" {
  description = "Per-student/instructor environment identity (non-secret)."
  type        = string
}

variable "my_ip_cidr" {
  description = "Explicit CIDR for application-port access."
  type        = string
  default     = "0.0.0.0/32" # no app access until set
}

variable "ssh_public_key_path" {
  description = "Controller-local SSH public key path."
  type        = string
}

variable "deploy_public_key_path" {
  description = "Controller-local S5 deploy public key path (null until enrolled in S5)."
  type        = string
  default     = null
}

variable "instructor_public_key_path" {
  description = "Controller-local instructor public key path (null until required at S6)."
  type        = string
  default     = null
}

variable "eip_allocation_id" {
  description = "EIP allocation id from the controller address state (consumed, not owned)."
  type        = string
}

variable "bootstrap_template_path" {
  description = "Bootstrap (cloud-init) template path; defaults to this root's cloud-init.yaml."
  type        = string
  default     = null
}

variable "instance_type" {
  description = "EC2 instance type. Containers profile (S4–S7) is t3.medium."
  type        = string
  default     = "t3.medium"
}

variable "app_ingress_cidrs" {
  description = "Explicit CIDRs for application ports."
  type        = list(string)
  default     = []
}

variable "cost_tags" {
  description = "Additional cost/ownership tags."
  type        = map(string)
  default     = {}
}

variable "k3s_enabled" {
  description = "S8: enable the pinned k3s platform on the operations (t3.large) phase."
  type        = bool
  default     = false
}

# operations-0.3.0 (S8+, from starter v1.3.0): must equal what the controller applied.
variable "root_volume_gb" {
  description = "Root volume size in GB (25 before operations-0.3.0; 30 from operations-0.3.0)."
  type        = number
  default     = 25
}

variable "web_ingress_cidrs" {
  description = "Explicit CIDRs allowed on TCP 80 (your S9 ingress rule)."
  type        = list(string)
  default     = []
}

variable "web_ingress_self" {
  description = "Allow TCP 80 from the VM's own EIP so the S10 probe (wb.<EIP>.sslip.io) reaches Traefik."
  type        = bool
  default     = false
}
