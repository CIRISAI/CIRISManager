# CIRISManager Research Infrastructure

Terraform configuration for CIRIS research infrastructure (manager + agents VMs).

> **Note**: This is **research infrastructure**, separate from production infrastructure managed in CIRISBridge.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Research Infrastructure                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────┐      ┌─────────────────────┐       │
│  │ ciris-manager       │      │ ciris-agents        │       │
│  │ 1 vCPU, 2 GB RAM    │      │ 2 vCPU, 4 GB RAM    │       │
│  │                     │      │                     │       │
│  │ • CIRISManager      │ VPC  │ • Agent containers  │       │
│  │ • Manager GUI       │<────>│ • ciris-gui         │       │
│  │ • nginx (routing)   │      │ • nginx             │       │
│  └─────────────────────┘      └─────────────────────┘       │
│         $12/mo                       $24/mo                 │
│                                                              │
│                    Total: ~$36/mo                           │
└─────────────────────────────────────────────────────────────┘
```

## Usage

### Prerequisites

- [Terraform](https://www.terraform.io/downloads) >= 1.0
- Vultr account with API key
- SSH key uploaded to Vultr

### Deploy

```bash
cd terraform

# Copy and configure variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your Vultr API key and SSH key ID

# Initialize terraform
terraform init

# Preview changes
terraform plan

# Apply (creates VMs)
terraform apply
```

### Post-Deployment

After `terraform apply`, you'll see outputs with:
- Public and VPC IPs for both VMs
- SSH config snippet
- CIRISManager config snippet for multi-server setup

#### 1. Configure SSH

Add the SSH config snippet to `~/.ssh/config`:

```bash
terraform output -raw ssh_config >> ~/.ssh/config
```

#### 2. Set up Docker TLS on agents VM

The manager needs TLS access to the agents VM Docker daemon:

```bash
# On agents VM
ssh ciris-agents

# Generate Docker TLS certs (see docs/DOCKER_TLS.md)
# Copy client certs to manager VM
```

#### 3. Install CIRISManager

```bash
ssh ciris-manager

# Clone and install
git clone https://github.com/CIRISAI/CIRISManager.git /opt/ciris-manager
cd /opt/ciris-manager
pip install -e .

# Configure
cp /etc/ciris-manager/config.yml.example /etc/ciris-manager/config.yml
# Edit config.yml with server entries from terraform output
```

## Sizing Reference

Based on production usage analysis:

| Component | Memory | CPU | Notes |
|-----------|--------|-----|-------|
| CIRISManager | ~100 MB | <1% | Systemd service |
| nginx | ~7 MB | <1% | Reverse proxy |
| Per agent | ~300 MB | 1-3% | Python + LLM calls |
| ciris-gui | ~80 MB | <1% | React container |

Manager VM (2GB) has headroom for growth.
Agents VM (4GB) can run ~10 agents comfortably.

## Cleanup

```bash
terraform destroy
```

## Files

| File | Purpose |
|------|---------|
| `main.tf` | VM and network resources |
| `variables.tf` | Configurable parameters |
| `outputs.tf` | Post-deployment information |
| `terraform.tfvars.example` | Example configuration |
