output "vm_id" { value = proxmox_virtual_environment_vm.platform.vm_id }
output "vm_ipv4" { value = split("/", var.vm_ipv4_cidr)[0] }
output "ssh_user" { value = var.ssh_user }
