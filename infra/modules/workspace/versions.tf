# RECOVERY-01: shared course workspace module. The initial controller root and
# the student S6 `ai-workbench/infra/` root consume THIS module at one pinned
# revision with identical resource addresses, so S6 adoption changes the
# editable root path — not resource identity (doc-18 §4).
terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
