resource "proxmox_download_file" "ubuntu" {
  node_name          = var.node_name
  datastore_id       = var.image_storage_id
  content_type       = "import"
  file_name          = "pl-ubuntu-26.04-20260927.qcow2"
  url                = var.cloud_image_url
  checksum           = "8800651811af9a85465ad1d552add729947bb16488dddb4a9b5305a3d97332b2"
  checksum_algorithm = "sha256"
  # The signed image is immutable and cached on Proxmox. Future plans must not
  # require the temporary bootstrap URL to remain reachable.
  overwrite = false
  lifecycle { prevent_destroy = true }
}

resource "proxmox_virtual_environment_file" "cloud_init" {
  node_name    = var.node_name
  datastore_id = var.image_storage_id
  content_type = "snippets"
  source_raw {
    file_name = "pl-${var.vm_id}-cloud-init.yaml"
    data = templatefile("${path.module}/cloud-init/user-data.yaml.tftpl", {
      ssh_user   = var.ssh_user
      public_key = trimspace(file(var.admin_ssh_public_key_path))
      hostname   = var.vm_name
      apt_proxy  = var.bootstrap_apt_proxy
    })
  }
  # Bootstrap is immutable after first boot; subsequent guest configuration is
  # owned by Ansible. Replacing this snippet would force VM replacement.
  lifecycle { ignore_changes = [source_raw[0].data] }
}

resource "proxmox_virtual_environment_vm" "platform" {
  node_name       = var.node_name
  vm_id           = var.vm_id
  name            = var.vm_name
  description     = "PrairieLearn: отдельная VM; state не связан с QCL-NEGF"
  tags            = ["prairielearn", "opentofu"]
  on_boot         = true
  started         = true
  stop_on_destroy = false
  scsi_hardware   = "virtio-scsi-single"
  cpu {
    cores = var.cpu_cores
    type  = "host"
    limit = var.cpu_cores
    units = 512
  }
  memory {
    dedicated = var.memory_mib
    floating  = 0
  }
  disk {
    datastore_id = var.system_storage_id
    import_from  = proxmox_download_file.ubuntu.id
    interface    = "scsi0"
    size         = var.disk_gib
    iothread     = true
  }
  network_device {
    bridge = var.network_bridge
    model  = "virtio"
  }
  initialization {
    datastore_id      = var.system_storage_id
    user_data_file_id = proxmox_virtual_environment_file.cloud_init.id
    dns { servers = var.dns_servers }
    ip_config {
      ipv4 {
        address = var.vm_ipv4_cidr
        gateway = var.vm_ipv4_gateway
      }
    }
  }
  agent { enabled = var.guest_agent_enabled }
  operating_system { type = "l26" }
  serial_device {}
  lifecycle { prevent_destroy = true }
}
