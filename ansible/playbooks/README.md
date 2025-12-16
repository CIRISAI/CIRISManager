# CIRIS Research Infrastructure Migration Playbooks

## Overview

These playbooks migrate CIRIS agents from old infrastructure to new, right-sized VMs with improved isolation and 40% cost reduction.

## Playbooks

| Playbook | Purpose |
|----------|---------|
| `migrate-all.yml` | **Master playbook** - runs all steps with confirmations |
| `01-backup-old-infrastructure.yml` | Backup agent data with checksums |
| `02-prepare-new-infrastructure.yml` | Setup directories, pull images |
| `03-transfer-data.yml` | Copy data to new servers |
| `04-deploy-containers.yml` | Deploy nginx, GUI, agents |
| `05-consensual-shutdown.yml` | Graceful agent shutdown with notification |
| `06-verify-migration.yml` | Health checks on new infrastructure |

## Quick Start

### Full Migration (Recommended)
```bash
cd /home/emoore/CIRISManager/ansible
ansible-playbook playbooks/migrate-all.yml
```

### Step-by-Step Migration
```bash
# Run each step individually
ansible-playbook playbooks/01-backup-old-infrastructure.yml
ansible-playbook playbooks/02-prepare-new-infrastructure.yml
ansible-playbook playbooks/03-transfer-data.yml
ansible-playbook playbooks/04-deploy-containers.yml
ansible-playbook playbooks/05-consensual-shutdown.yml
ansible-playbook playbooks/06-verify-migration.yml
```

### Verify Only (No Changes)
```bash
ansible-playbook playbooks/06-verify-migration.yml --check
```

## Features

- **Health Checks**: Every step verifies container health before proceeding
- **Rollback Handlers**: Failed deployments trigger automatic cleanup
- **Checksum Verification**: Backups include SHA256 checksums
- **Consensual Shutdown**: Agents receive migration notification before stopping
- **Idempotent**: Safe to re-run playbooks

## Infrastructure

### Old (To Be Decommissioned)
- `old_main` (108.61.119.117): 4 vCPU, 16GB - ~$70/mo
- `old_scout1` (207.148.14.113): 1 vCPU, 3.4GB - ~$12/mo
- `old_scout2` (104.207.141.1): 2 vCPU, 3.4GB - ~$18/mo

### New (Migration Targets)
- `new_manager` (45.76.226.222): 1 vCPU, 2GB - $12/mo
- `new_agents` (45.76.231.182): 2 vCPU, 4GB - $24/mo
- `new_scout1` (144.202.55.195): 1 vCPU, 2GB - $12/mo
- `new_scout2` (45.76.18.133): 1 vCPU, 2GB - $12/mo

**Monthly Savings: $40 (40%)**

## Variables

Key variables in `group_vars/all.yml`:
- `migration_message`: Message sent to agents during shutdown
- `health_check_retries`: Number of health check attempts (default: 10)
- `health_check_delay`: Seconds between retries (default: 5)
- `rollback_on_failure`: Enable automatic rollback (default: true)

## Requirements

- Ansible 2.10+
- `community.docker` collection: `ansible-galaxy collection install community.docker`
- SSH access to all servers via `~/.ssh/ciris_deploy`

## Post-Migration

1. **Update DNS** in Cloudflare:
   - `manager.ciris.ai` -> 45.76.226.222
   - `agents.ciris.ai` -> 45.76.231.182
   - `scoutapi.ciris.ai` -> 144.202.55.195

2. **Monitor** for 48-72 hours

3. **Decommission** old VMs after confirming stability
