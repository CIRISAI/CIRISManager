# CIRISManager Research Infrastructure
#
# This provisions VMs for CIRIS research workloads (manager + agents).
# Production infrastructure (CIRISLens, CIRISBridge) is managed separately.
#
# Usage:
#   cp terraform.tfvars.example terraform.tfvars
#   # Edit terraform.tfvars with your values
#   terraform init
#   terraform plan
#   terraform apply

terraform {
  required_version = ">= 1.0"

  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.0"
    }
  }
}

provider "vultr" {
  api_key = var.vultr_api_key
}

# VPC for internal communication between manager and agents
resource "vultr_vpc" "research" {
  description    = var.vpc_description
  region         = var.region
  v4_subnet      = var.vpc_subnet
  v4_subnet_mask = var.vpc_subnet_size
}

# Manager VM - runs CIRISManager service, nginx routing, manager GUI
resource "vultr_instance" "manager" {
  region    = var.region
  plan      = var.manager_plan
  os_id     = var.os_id
  hostname  = var.manager_hostname
  label     = var.manager_label
  ssh_key_ids = var.ssh_key_ids

  vpc_ids = [vultr_vpc.research.id]

  tags = [
    var.environment,
    var.project,
    "manager"
  ]

  # Cloud-init to set up basic requirements
  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # Update system
    apt-get update && apt-get upgrade -y

    # Install Docker
    curl -fsSL https://get.docker.com | sh

    # Install Python 3.11+ for CIRISManager
    apt-get install -y python3.11 python3.11-venv python3-pip

    # Create ciris user
    useradd -m -s /bin/bash ciris || true
    usermod -aG docker ciris

    # Create directories
    mkdir -p /opt/ciris-manager /opt/ciris/agents /opt/ciris/nginx
    chown -R ciris:ciris /opt/ciris /opt/ciris-manager

    # Enable Docker
    systemctl enable docker
    systemctl start docker
  EOF
}

# Agents VM - runs agent containers, GUI container, nginx
resource "vultr_instance" "agents" {
  region    = var.region
  plan      = var.agents_plan
  os_id     = var.os_id
  hostname  = var.agents_hostname
  label     = var.agents_label
  ssh_key_ids = var.ssh_key_ids

  vpc_ids = [vultr_vpc.research.id]

  tags = [
    var.environment,
    var.project,
    "agents"
  ]

  # Cloud-init to set up Docker and agent requirements
  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # Update system
    apt-get update && apt-get upgrade -y

    # Install Docker
    curl -fsSL https://get.docker.com | sh

    # Create ciris user
    useradd -m -s /bin/bash ciris || true
    usermod -aG docker ciris

    # Create directories
    mkdir -p /opt/ciris/agents /opt/ciris/nginx
    chown -R ciris:ciris /opt/ciris

    # Enable Docker
    systemctl enable docker
    systemctl start docker

    # Configure Docker daemon for TLS (manager will connect remotely)
    # TLS certs must be provisioned separately after instance creation
    mkdir -p /etc/docker/certs
  EOF
}

# Firewall for manager VM
resource "vultr_firewall_group" "manager" {
  description = "CIRIS Manager firewall rules"
}

resource "vultr_firewall_rule" "manager_ssh" {
  firewall_group_id = vultr_firewall_group.manager.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "22"
  notes             = "SSH access"
}

resource "vultr_firewall_rule" "manager_http" {
  firewall_group_id = vultr_firewall_group.manager.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "80"
  notes             = "HTTP (ACME challenges)"
}

resource "vultr_firewall_rule" "manager_https" {
  firewall_group_id = vultr_firewall_group.manager.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "443"
  notes             = "HTTPS"
}

resource "vultr_firewall_rule" "manager_api_from_vpc" {
  firewall_group_id = vultr_firewall_group.manager.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = var.vpc_subnet
  subnet_size       = var.vpc_subnet_size
  port              = "8888"
  notes             = "Manager API from VPC (agents proxy)"
}

# Firewall for agents VM
resource "vultr_firewall_group" "agents" {
  description = "CIRIS Agents firewall rules"
}

resource "vultr_firewall_rule" "agents_ssh" {
  firewall_group_id = vultr_firewall_group.agents.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "22"
  notes             = "SSH access"
}

resource "vultr_firewall_rule" "agents_http" {
  firewall_group_id = vultr_firewall_group.agents.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "80"
  notes             = "HTTP (ACME challenges)"
}

resource "vultr_firewall_rule" "agents_https" {
  firewall_group_id = vultr_firewall_group.agents.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "443"
  notes             = "HTTPS"
}

resource "vultr_firewall_rule" "agents_docker_from_vpc" {
  firewall_group_id = vultr_firewall_group.agents.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = var.vpc_subnet
  subnet_size       = var.vpc_subnet_size
  port              = "2376"
  notes             = "Docker TLS API from VPC only"
}

# Scout1 VM - additional agent capacity
resource "vultr_instance" "scout1" {
  region            = var.region
  plan              = var.scout1_plan
  os_id             = var.os_id
  hostname          = var.scout1_hostname
  label             = var.scout1_label
  ssh_key_ids       = var.ssh_key_ids
  firewall_group_id = vultr_firewall_group.scout.id

  vpc_ids = [vultr_vpc.research.id]

  tags = [
    var.environment,
    var.project,
    "scout"
  ]

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # Update system
    apt-get update && apt-get upgrade -y

    # Install Docker
    curl -fsSL https://get.docker.com | sh

    # Create ciris user
    useradd -m -s /bin/bash ciris || true
    usermod -aG docker ciris

    # Create directories
    mkdir -p /opt/ciris/agents /opt/ciris/nginx /home/ciris/shared /etc/docker/certs
    chown -R ciris:ciris /opt/ciris /home/ciris

    # Enable Docker
    systemctl enable docker
    systemctl start docker

    # Configure UFW firewall
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow from ${var.vpc_subnet}/${var.vpc_subnet_size} to any port 2376 proto tcp
    ufw --force enable
  EOF
}

# Scout2 VM - additional agent capacity
resource "vultr_instance" "scout2" {
  region            = var.region
  plan              = var.scout2_plan
  os_id             = var.os_id
  hostname          = var.scout2_hostname
  label             = var.scout2_label
  ssh_key_ids       = var.ssh_key_ids
  firewall_group_id = vultr_firewall_group.scout.id

  vpc_ids = [vultr_vpc.research.id]

  tags = [
    var.environment,
    var.project,
    "scout"
  ]

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # Update system
    apt-get update && apt-get upgrade -y

    # Install Docker
    curl -fsSL https://get.docker.com | sh

    # Create ciris user
    useradd -m -s /bin/bash ciris || true
    usermod -aG docker ciris

    # Create directories
    mkdir -p /opt/ciris/agents /opt/ciris/nginx /home/ciris/shared /etc/docker/certs
    chown -R ciris:ciris /opt/ciris /home/ciris

    # Enable Docker
    systemctl enable docker
    systemctl start docker

    # Configure UFW firewall
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow from ${var.vpc_subnet}/${var.vpc_subnet_size} to any port 2376 proto tcp
    ufw --force enable
  EOF
}

# Firewall for scout VMs (shared)
resource "vultr_firewall_group" "scout" {
  description = "CIRIS Scout firewall rules"
}

resource "vultr_firewall_rule" "scout_ssh" {
  firewall_group_id = vultr_firewall_group.scout.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "22"
  notes             = "SSH access"
}

resource "vultr_firewall_rule" "scout_http" {
  firewall_group_id = vultr_firewall_group.scout.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "80"
  notes             = "HTTP (ACME challenges)"
}

resource "vultr_firewall_rule" "scout_https" {
  firewall_group_id = vultr_firewall_group.scout.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "443"
  notes             = "HTTPS"
}

resource "vultr_firewall_rule" "scout_docker_from_vpc" {
  firewall_group_id = vultr_firewall_group.scout.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = var.vpc_subnet
  subnet_size       = var.vpc_subnet_size
  port              = "2376"
  notes             = "Docker TLS API from VPC only"
}
