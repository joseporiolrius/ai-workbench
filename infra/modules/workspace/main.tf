# Workspace resources: network, firewall, key, VM and address association.
# The module OWNS these; it CONSUMES the supplied EIP allocation and never
# owns aws_eip (ENV-R007 / doc-18 §3).

locals {
  name = "dbai-${var.student_id}"

  # Inbound PUBLIC access keys enrolled for this environment. Student key is
  # always present; deploy (S5) and instructor (S6) enroll when their path is
  # supplied. No private key material is ever read here.
  authorized_keys = compact(concat(
    [trimspace(file(var.ssh_public_key_path))],
    var.deploy_public_key_path != null ? [trimspace(file(var.deploy_public_key_path))] : [],
    var.instructor_public_key_path != null ? [trimspace(file(var.instructor_public_key_path))] : [],
  ))

  # Explicit application-port CIDRs (doc-18: SSH is 0.0.0.0/0 key-only, app
  # ports are explicit). my_ip_cidr is the caller's single "my IP"; the
  # "0.0.0.0/32" sentinel means "no app access". app_ingress_cidrs adds any
  # extra explicit CIDRs. The app rule is created only when at least one real
  # CIDR is present.
  app_cidrs = distinct(compact(concat(
    var.my_ip_cidr == "0.0.0.0/32" ? [] : [var.my_ip_cidr],
    var.app_ingress_cidrs,
  )))

  tags = merge({
    Project     = "ec2-console"
    Course      = "dbai"
    ManagedBy   = "terraform"
    Environment = var.student_id
    Component   = "workspace"
  }, var.cost_tags)
}

# Ubuntu 24.04 LTS AMI for the SELECTED region (avoids wrong-region/old AMIs).
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# --- network ---------------------------------------------------------------
resource "aws_vpc" "this" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = local.name })
}

resource "aws_subnet" "this" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = false # the persistent EIP provides public addressing
  tags                    = merge(local.tags, { Name = "${local.name}-public" })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = local.name })
}

resource "aws_route_table" "this" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = merge(local.tags, { Name = local.name })
}

resource "aws_route_table_association" "this" {
  subnet_id      = aws_subnet.this.id
  route_table_id = aws_route_table.this.id
}

# Lock down the VPC's default security group (CKV2_AWS_12): no ingress/egress
# rules means deny-all, so nothing can implicitly rely on an open default SG.
# The workspace instance uses aws_security_group.this, not this one.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${local.name}-default-deny" })
}

# --- firewall --------------------------------------------------------------
resource "aws_security_group" "this" {
  name        = "${local.name}-sg"
  description = "DBAI workspace: key-only SSH; explicit application CIDRs"
  vpc_id      = aws_vpc.this.id
  tags        = merge(local.tags, { Name = local.name })

  # SSH is key-only; 0.0.0.0/0 is required so hosted CI runners can reach it.
  ingress {
    description = "SSH (key-only)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Application ports are opened ONLY to explicit CIDRs (my_ip_cidr + extras).
  dynamic "ingress" {
    for_each = length(local.app_cidrs) > 0 ? [1] : []
    content {
      description = "Application ports (explicit CIDRs)"
      from_port   = 8888
      to_port     = 8889
      protocol    = "tcp"
      cidr_blocks = local.app_cidrs
    }
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- key -------------------------------------------------------------------
resource "aws_key_pair" "this" {
  key_name   = "${local.name}-key"
  public_key = file(var.ssh_public_key_path)
  tags       = local.tags
}

# --- VM --------------------------------------------------------------------
resource "aws_instance" "this" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.this.id
  vpc_security_group_ids = [aws_security_group.this.id]
  key_name               = aws_key_pair.this.key_name

  # Require IMDSv2 (CKV_AWS_79): blocks SSRF-style theft of the instance role
  # credentials over IMDSv1. Ubuntu 24.04 cloud-init and modern AWS SDKs speak
  # IMDSv2, so bootstrap and tooling are unaffected.
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  # Caller's bootstrap template, rendered with the enrolled PUBLIC keys. The
  # template file is byte-identical across the controller and S6 roots; equal
  # inputs render an equal result (RECOVERY-02).
  user_data = templatefile(var.bootstrap_template_path, {
    authorized_keys = local.authorized_keys
  })

  root_block_device {
    volume_size = 25
    volume_type = "gp3"
  }

  tags = merge(local.tags, { Name = local.name })
}

# --- address association (consumes the supplied EIP; owns no aws_eip) -------
resource "aws_eip_association" "this" {
  allocation_id = var.eip_allocation_id
  instance_id   = aws_instance.this.id
}
