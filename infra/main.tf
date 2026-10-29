# DBAI S6 student workspace root (RECOVERY-03).
#
# This is the reviewable Terraform root you ADOPT in S6. It consumes the SAME
# pinned course workspace module (RECOVERY-01), at the SAME resource addresses,
# with the SAME provider config and inputs as the controller's initial root
# (ec2-console dbai/terraform/workspace). Adopting it therefore changes only the
# editable root path — not resource identity — so `terraform plan` against the
# controller-generated state is a ZERO-CHANGE plan (doc-18 §4). See EQUIVALENCE.md.
#
# State, credentials, private keys and binary plans stay on the controller and
# are NOT versioned here (see .gitignore, BACKEND via backend.hcl.example).

terraform {
  required_version = ">= 1.9"

  backend "local" {
    # `path` is injected at init time by the controller:
    #   terraform init -backend-config=path=<controller-state>/workspace.tfstate
    # (see backend.hcl.example). State is controller-owned and never committed.
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # IDENTICAL to the controller root, so no provider-driven diffs on adoption.
  default_tags {
    tags = {
      Project     = "ec2-console"
      Course      = "dbai"
      ManagedBy   = "terraform"
      Environment = var.student_id
    }
  }
}

# IDENTICAL module block name ("workspace") and wiring as the controller root,
# so every resource keeps the address module.workspace.aws_*. The module is the
# pinned shared module, vendored under ./modules/workspace (see MODULE_PROVENANCE.md).
module "workspace" {
  source = "./modules/workspace"

  student_id                  = var.student_id
  aws_region                  = var.aws_region
  my_ip_cidr                  = var.my_ip_cidr
  ssh_public_key_path         = var.ssh_public_key_path
  deploy_public_key_path      = var.deploy_public_key_path
  instructor_public_key_path  = var.instructor_public_key_path
  eip_allocation_id           = var.eip_allocation_id
  bootstrap_template_path     = coalesce(var.bootstrap_template_path, "${path.root}/cloud-init.yaml")
  instance_type               = var.instance_type
  k3s_enabled                 = var.k3s_enabled
  user_data_replace_on_change = var.k3s_enabled
  app_ingress_cidrs           = var.app_ingress_cidrs
  root_volume_gb              = var.root_volume_gb
  web_ingress_cidrs           = var.web_ingress_cidrs
  web_ingress_self            = var.web_ingress_self
  cost_tags                   = var.cost_tags
}
