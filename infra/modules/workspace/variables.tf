# Canonical module inputs (RECOVERY-R002). The pre-S8 interface intentionally
# does NOT include k3s_enabled — that arrives with the S8 profile boundary.

variable "student_id" {
  description = "Per-student/environment identity (non-secret); used in names/tags."
  type        = string
  validation {
    condition     = length(var.student_id) > 0
    error_message = "student_id must not be empty."
  }
}

variable "aws_region" {
  description = "AWS region for the workspace."
  type        = string
}

variable "my_ip_cidr" {
  description = "Explicit CIDR allowed to reach application ports (never a blanket default)."
  type        = string
  validation {
    condition     = can(cidrhost(var.my_ip_cidr, 0))
    error_message = "my_ip_cidr must be a valid CIDR (e.g. 203.0.113.4/32)."
  }
}

variable "ssh_public_key_path" {
  description = "Controller-local path to the student's SSH public key (login key)."
  type        = string
  validation {
    condition     = fileexists(var.ssh_public_key_path)
    error_message = "ssh_public_key_path does not exist on the controller."
  }
}

# Optional: enrolled before S6 (S5). Public key only; private key never here.
variable "deploy_public_key_path" {
  description = "Controller-local S5 deploy public key path (null until enrolled in S5)."
  type        = string
  default     = null
  validation {
    condition     = var.deploy_public_key_path == null || fileexists(coalesce(var.deploy_public_key_path, "/"))
    error_message = "deploy_public_key_path is set but does not exist on the controller."
  }
}

# Optional: required from S6. The instructor public key for assigned-environment
# fault injection (RECOVERY-R008). Public key only.
variable "instructor_public_key_path" {
  description = "Controller-local instructor public key path (null until required at S6)."
  type        = string
  default     = null
  validation {
    condition     = var.instructor_public_key_path == null || fileexists(coalesce(var.instructor_public_key_path, "/"))
    error_message = "instructor_public_key_path is set but does not exist on the controller."
  }
}

variable "eip_allocation_id" {
  description = "EIP allocation ID from the independent address state. Consumed, never owned."
  type        = string
  validation {
    condition     = can(regex("^eipalloc-", var.eip_allocation_id))
    error_message = "eip_allocation_id must be an eipalloc-* id from the address state."
  }
}

variable "bootstrap_template_path" {
  description = "Controller-local path to the bootstrap (cloud-init) template. Used byte-identically."
  type        = string
  validation {
    condition     = fileexists(var.bootstrap_template_path)
    error_message = "bootstrap_template_path does not exist."
  }
}

variable "instance_type" {
  description = "EC2 instance type (from the phase profile, e.g. t3.small)."
  type        = string
  validation {
    condition     = length(var.instance_type) > 0
    error_message = "instance_type must not be empty."
  }
}

variable "app_ingress_cidrs" {
  description = "Explicit CIDRs allowed to reach application ports (8888-8889). No implicit 0.0.0.0/0."
  type        = list(string)
  default     = []
}

variable "cost_tags" {
  description = "Additional cost/ownership tags merged onto every resource."
  type        = map(string)
  default     = {}
}
