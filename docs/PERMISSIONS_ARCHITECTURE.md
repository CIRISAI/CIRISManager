# CIRIS Permission Architecture

## Overview
This document explains how permissions are managed between CIRISManager and CIRIS agent containers.

## The Permission Challenge
- **CIRISManager** runs as system service user `ciris-manager` (created by systemd)
- **CIRIS Agent containers** run as user `ciris` (uid=1005, gid=1005)
- **Problem**: Files created by manager aren't writable by containers

## Division of Responsibilities

### CIRISManager (runs on host as `ciris-manager` user)
**What it does:**
1. Creates agent directory structure at `/opt/ciris/agents/{agent_id}/`
2. Sets Unix permissions (755 for most dirs, 700 for secrets)
3. **Changes ownership to `ciris:ciris`** so containers can write
4. Copies init_permissions.sh script to agent directory
5. Generates docker-compose.yml with bind mounts

**Key code location:** `ciris_manager/manager.py` lines 241-272

### init_permissions.sh (runs inside container as `ciris` user)
**What it does:**
1. Verifies directories exist and are writable
2. Creates missing directories if needed
3. Attempts to fix permissions if directories aren't writable
4. Reports any permission issues that can't be fixed

**Key limitations:**
- Cannot change ownership (needs root/sudo)
- Can only create/modify files owned by `ciris` user
- Primarily a safety check, not the primary permission setter

## How It Works

1. **Agent Creation:**
   - Manager creates directories owned by `ciris-manager`
   - Manager runs `chown -R ciris:ciris /opt/ciris/agents/{agent_id}`
   - Directories now owned by `ciris` user

2. **Container Startup:**
   - Docker compose mounts host directories into container
   - init_permissions.sh runs as entrypoint
   - Script verifies write access and creates test files
   - If successful, starts the CIRIS agent

3. **Bind Mounts:**
   ```yaml
   volumes:
     - /opt/ciris/agents/{agent_id}/data:/app/data
     - /opt/ciris/agents/{agent_id}/logs:/app/logs
     - /opt/ciris/agents/{agent_id}/.secrets:/app/.secrets
   ```
   - Host paths owned by `ciris:ciris`
   - Container runs as `ciris:ciris`
   - Perfect permission match!

## Troubleshooting

### Agent exits with permission errors
1. Check host directory ownership: `ls -la /opt/ciris/agents/{agent_id}/`
2. Should show `ciris ciris` as owner
3. If not, fix with: `chown -R ciris:ciris /opt/ciris/agents/{agent_id}/`

### Manager can't change ownership
- Manager must run as root or have sudo privileges for chown
- Systemd service runs as `ciris-manager` user
- Service configuration may need `User=root` or sudoers entry

## Security Considerations

- `.secrets` and `audit_keys` directories have 700 permissions (owner only)
- Other directories have 755 permissions (world readable)
- Service tokens stored encrypted in agent registry
- OAuth shared volume mounted read-only
