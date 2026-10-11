terraform {
  backend "local" {}
  required_version = ">= 1.13.0, < 2.0.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.116.0"
    }
  }
}
