# Same outputs as the controller root, read straight from the shared module.

output "public_ip" {
  description = "Persistent public IP of the workspace (the course-contract address)."
  value       = module.workspace.public_ip
}

output "instance_id" {
  description = "Workspace VM instance id."
  value       = module.workspace.instance_id
}
