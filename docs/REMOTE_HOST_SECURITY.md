# Remote Agent Host Security Model

## Overview

Remote agent hosts (like scout.ciris.ai) are secure container environments managed remotely by the main CIRISManager instance. This document outlines the security architecture.

## Security Principles

1. **Least Privilege**: Each component runs with minimum required permissions
2. **Defense in Depth**: Multiple layers of security (firewall, TLS, user isolation)
3. **Secure by Default**: Default configuration is secure, requires explicit changes to weaken
4. **Audit Trail**: All file permissions allow read access for monitoring/debugging

## User and Permission Model

### Host Users

| User | UID | Purpose | Docker Access |
|------|-----|---------|---------------|
| root | 0 | System administration only | Yes (full) |
| ciris | 1000 | Owns agent data, matches container user | Yes (via docker group) |

### Container Users

All CIRIS agent containers run as user `ciris` (uid 1000) inside the container. This **matches** the host `ciris` user for seamless file permission handling.

### File Ownership

```
/opt/ciris/                          # ciris:ciris 755
├── agents/                          # ciris:ciris 755
│   └── {agent_id}/
│       ├── data/                    # 1000:1000 755 (readable audit trail)
│       ├── data_archive/            # 1000:1000 755 (archived thoughts/tasks)
│       ├── logs/                    # 1000:1000 755 (readable for monitoring)
│       ├── config/                  # 1000:1000 755 (config is public)
│       ├── .secrets/                # 1000:1000 700 (private credentials)
│       └── audit_keys/              # 1000:1000 700 (private signing keys)
└── nginx/                           # ciris:ciris 755
    └── nginx.conf                   # ciris:ciris 644
```

**Why uid 1000 matches:**
- Host ciris user: uid 1000
- Container ciris user: uid 1000
- Files created in container are owned by host ciris user
- No permission issues when managing files from host

## Docker Security

### Daemon Configuration

```json
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://10.x.x.x:2376"],
  "tls": true,
  "tlsverify": true,
  "tlscacert": "/etc/docker/certs/ca.pem",
  "tlscert": "/etc/docker/certs/server-cert.pem",
  "tlskey": "/etc/docker/certs/server-key.pem"
}
```

**Security features:**
- **TLS required**: No unencrypted connections
- **Mutual TLS**: Client must present valid certificate (signed by CA)
- **VPC-only binding**: Listens on VPC IP (10.x.x.x), not public interface
- **Local socket**: Unix socket for local docker commands (ciris user access)

### Certificate Chain

```
CA Certificate (ca.pem)
├── Server Certificate (server-cert.pem)
│   - Used by Docker daemon
│   - SAN: DNS:scout.ciris.ai, IP:10.2.96.4, IP:207.148.14.113
│   - Extended usage: serverAuth
│
└── Client Certificate (client-cert.pem)
    - Used by main server's CIRISManager
    - CN: ciris-manager
    - Extended usage: clientAuth
```

**Certificate lifecycle:**
- Validity: 10 years (3650 days)
- Algorithm: RSA 4096-bit
- Hash: SHA-256
- Stored at: `/etc/docker/certs/`
- Permissions: 0400 (private keys), 0444 (public certs)

## Network Security

### Firewall Rules (UFW)

```bash
# Public access
ufw allow 22/tcp        # SSH
ufw allow 80/tcp        # HTTP (redirect to HTTPS)
ufw allow 443/tcp       # HTTPS (nginx)

# Docker API - VPC ONLY
ufw deny 2376/tcp                              # Block from public
ufw allow from 10.0.0.0/8 to any port 2376   # Allow from VPC
```

**Result:**
- Docker API (port 2376) is **blocked** from public internet
- Only accessible from VPC network (10.0.0.0/8)
- Main server can connect via VPC IP

### Network Topology

```
Internet (Public)
   ↓
   443/80 → Nginx Container (TLS termination)
             ↓
             127.0.0.1:8080+ → Agent Containers
                                (local network)

Main Server (VPC: 10.x.x.x)
   ↓
   2376/tcp → Docker API (mutual TLS)
              (VPC IP: 10.2.96.4)
              ↓
              Container Management

Public Internet (blocked)
   ✗
   2376/tcp → Firewall DROP
```

### TLS Termination

**Nginx handles all public TLS:**
- Let's Encrypt certificates for `scout.ciris.ai`
- Automatic renewal via certbot
- HTTPS → HTTP proxy to local containers
- End-to-end encryption: Browser → Nginx (HTTPS), Nginx → Agent (HTTP/localhost)

## Container Security

### Container Runtime

All CIRIS agent containers:
- Run as **non-root user** (uid 1000 / ciris)
- No privileged mode
- No host network mode (except nginx)
- Read-only root filesystem where possible
- Explicit volume mounts only (no full filesystem access)

### Nginx Container

Special case - runs in **host network mode**:
- Needs to bind to ports 80/443 directly
- Runs as nginx user inside container (not root)
- Read-only config volume mount
- No write access to host filesystem

### Environment Isolation

Each agent container is isolated:
- Separate Docker network per agent
- No inter-agent communication
- Environment variables scoped per agent
- Volume mounts scoped to agent directory only

## Remote Management Security

### CIRISManager Access

Main server's CIRISManager connects to remote Docker API via:

1. **TLS Client Certificate**: Proves identity as authorized manager
2. **VPC Network**: Connection from VPC IP (not public)
3. **Mutual TLS**: Both client and server verify each other
4. **No Password Auth**: Certificate-based only

### Operations Allowed

CIRISManager can:
- Start/stop containers
- Pull images
- Create volumes
- Update nginx config
- Read logs

CIRISManager **cannot**:
- SSH to host
- Modify TLS certificates
- Change Docker daemon config
- Access root filesystem outside /opt/ciris

## Monitoring and Auditing

### Log Accessibility

All logs are **readable** (755 permissions):
- Agent logs: `/opt/ciris/agents/{id}/logs/`
- Container logs: `docker logs ciris-{id}`
- Nginx logs: `/var/log/nginx/` (in nginx container)

**Why readable:**
- Enables monitoring and debugging
- Audit trail for compliance
- No secrets in logs (secrets in `.secrets/` dir)

### Audit Requirements

Per CIRIS File Permission System:
- **Data directory (755)**: Database audit trail must be accessible
- **Logs (755)**: All actions must be auditable
- **Secrets (700)**: Credentials protected but not logged
- **Audit keys (700)**: Signing keys protected for integrity

## Incident Response

### Compromise Scenarios

**If remote host is compromised:**
1. Revoke client certificate on main server
2. Main server loses Docker API access
3. Containers continue running (isolated)
4. User traffic unaffected (Cloudflare → nginx still works)

**If Docker API is exploited:**
1. Firewall limits to VPC only
2. TLS cert must be stolen for access
3. Containers run as non-root (limited damage)
4. Host filesystem outside /opt/ciris is protected

**If container is compromised:**
1. Limited to non-root user (uid 1000)
2. No access to other containers
3. No access to Docker socket
4. Volume mounts limited to agent directory

### Recovery Procedures

1. **Rotate TLS Certificates**: Re-run setup_remote.sh
2. **Reset Remote Host**: Nuke and rebuild from script
3. **Audit Agent Data**: Check `/opt/ciris/agents/{id}/logs/` for anomalies
4. **Review Firewall Logs**: Check for unauthorized access attempts

## Best Practices

### For Production Deployment

1. ✅ Use `setup_remote.sh` script (enforces security)
2. ✅ Keep TLS client certs on main server only
3. ✅ Verify firewall rules block public Docker API access
4. ✅ Monitor Docker API access logs
5. ✅ Regular security updates via automated deployments
6. ✅ Use named volumes for agent data (portable, secure)

### For Development/Testing

1. ⚠️ Never disable TLS verification
2. ⚠️ Never expose Docker API to public internet
3. ⚠️ Never run containers as root user
4. ⚠️ Test firewall rules before production use

## Setup Script Usage

### Initial Setup

```bash
# From main server or local machine
cd /home/emoore/CIRISManager/scripts
./setup_remote.sh scout.ciris.ai 10.2.96.4 207.148.14.113

# Script will:
# 1. SSH to remote server
# 2. Install Docker with TLS
# 3. Create ciris user
# 4. Generate certificates
# 5. Configure firewall
# 6. Download client certs to ./docker-certs-scout.ciris.ai/
```

### Copy Certificates to Main Server

```bash
# On main production server (agents.ciris.ai)
ssh -i ~/.ssh/ciris_deploy root@108.61.119.117

mkdir -p /etc/ciris-manager/docker-certs/scout
scp user@local:docker-certs-scout.ciris.ai/* /etc/ciris-manager/docker-certs/scout/
chmod 600 /etc/ciris-manager/docker-certs/scout/client-key.pem
chmod 644 /etc/ciris-manager/docker-certs/scout/{ca,client-cert}.pem
```

### Test Connection

```bash
# From main server
docker -H tcp://10.2.96.4:2376 \
  --tlsverify \
  --tlscacert /etc/ciris-manager/docker-certs/scout/ca.pem \
  --tlscert /etc/ciris-manager/docker-certs/scout/client-cert.pem \
  --tlskey /etc/ciris-manager/docker-certs/scout/client-key.pem \
  ps
```

## Compliance Notes

### CIRIS File Permission System

This security model implements the CIRIS File Permission System requirements:

✅ **Data (755)**: Database files readable for audit trail
✅ **Logs (755)**: All logs accessible for monitoring
✅ **Config (755)**: Configuration is public
✅ **Secrets (700)**: Credentials protected from unauthorized access
✅ **Audit Keys (700)**: Signing keys secured to prevent compromise

### Key Security Controls

- ✅ **Authentication**: Mutual TLS (certificate-based)
- ✅ **Authorization**: Firewall restricts API to VPC
- ✅ **Encryption**: TLS 1.2+ for all Docker API communication
- ✅ **Isolation**: Containers run as non-root, separate networks
- ✅ **Audit**: All operations logged, files readable
- ✅ **Least Privilege**: Each component has minimum required access
