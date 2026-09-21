# public_ip is the persistent Elastic IP now associated with the VM — the
# stable course-contract address (VM_HOST / deployed URLs).
data "aws_eip" "assigned" {
  id         = var.eip_allocation_id
  depends_on = [aws_eip_association.this]
}

output "public_ip" {
  description = "Persistent public IP (the associated EIP)."
  value       = data.aws_eip.assigned.public_ip
}

output "instance_id" {
  description = "Workspace VM instance id."
  value       = aws_instance.this.id
}

output "vpc_id" {
  description = "Workspace VPC id."
  value       = aws_vpc.this.id
}

output "security_group_id" {
  description = "Workspace security group id."
  value       = aws_security_group.this.id
}

output "ami_id" {
  description = "Resolved Ubuntu 24.04 AMI id for the region."
  value       = data.aws_ami.ubuntu.id
}
