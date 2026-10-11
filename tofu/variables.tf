variable "proxmox_endpoint" {
  type = string
}

variable "proxmox_ssh_address" {
  type = string
}

variable "cloud_image_url" {
  type        = string
  default     = "https://cloud-images.ubuntu.com/releases/resolute/release-20260927/ubuntu-26.04-server-cloudimg-amd64.img"
  description = "Официальный URL или временный relay тех же байтов; signed checksum остаётся фиксированным."
}

variable "bootstrap_apt_proxy" {
  type    = string
  default = ""
}

variable "guest_agent_enabled" {
  type        = bool
  default     = false
  description = "Включить после подтверждённой установки qemu-guest-agent внутри гостя."
}

variable "proxmox_ssh_key_path" {
  type = string
}

variable "admin_ssh_public_key_path" {
  type = string
}

variable "node_name" {
  type = string
}

variable "image_storage_id" {
  type    = string
  default = "local"
}

variable "system_storage_id" {
  type    = string
  default = "local-lvm"
}

variable "network_bridge" {
  type    = string
  default = "vmbr0"
}

variable "vm_id" {
  type = number
}

variable "vm_name" {
  type    = string
  default = "prairielearn-pilot"
}

variable "ssh_user" {
  type    = string
  default = "pladmin"
}

variable "cpu_cores" {
  type    = number
  default = 4
}

variable "memory_mib" {
  type    = number
  default = 8192
}

variable "disk_gib" {
  type    = number
  default = 60
}

variable "vm_ipv4_cidr" {
  type = string
  validation {
    condition     = can(cidrhost(var.vm_ipv4_cidr, 0))
    error_message = "Нужен IPv4 CIDR."
  }
}

variable "vm_ipv4_gateway" {
  type = string
}

variable "dns_servers" {
  type = list(string)
}
