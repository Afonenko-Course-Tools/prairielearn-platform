provider "proxmox" {
  endpoint = var.proxmox_endpoint
  insecure = false
  ssh {
    username    = "root"
    agent       = false
    private_key = file(var.proxmox_ssh_key_path)
    node {
      name    = var.node_name
      address = var.proxmox_ssh_address
    }
  }
}
