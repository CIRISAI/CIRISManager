# Remote Server Management

This document describes the complete lifecycle of remote agent servers in CIRISManager, from initial setup to agent deployment and ongoing management.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Initial Server Setup](#initial-server-setup)
- [Directory Structure](#directory-structure)
- [Shared Files](#shared-files)
- [OAuth Configuration](#oauth-configuration)
- [Agent Deployment](#agent-deployment)
- [Nginx Configuration](#nginx-configuration)
- [Permissions Management](#permissions-management)
- [Docker API Security](#docker-api-security)
- [Troubleshooting](#troubleshooting)

## Overview

CIRISManager supports deploying agents across multiple physical servers, enabling horizontal scaling and geographic distribution. Remote servers are managed via Docker API over TLS, with all configuration and deployment orchestrated centrally from the main server.

### Key Features

- **Centralized Management**: All operations initiated from main server
- **Secure Communication**: Docker API over TLS (port 2376)
- **Automatic Configuration**: Nginx configs deployed remotely
- **Shared Resources**: Common scripts and OAuth configs synced once per server
- **Permission Handling**: Automated permission fixes for container access

## Architecture

```
Main Server (agents.ciris.ai)
├── CIRISManager Service
│   ├── Multi-Server Docker Client
│   ├── Agent Registry
│   └── Nginx Manager
└── Docker API Client (local socket)

Remote Server (scoutapi.ciris.ai)
├── Docker API (TLS on VPC IP:2376)
│   ├── ciris-nginx container
│   └── ciris-{agent_id} containers
├── /opt/ciris/
│   ├── agents/           # Agent data directories
│   └── nginx/            # Nginx configuration
└── /home/ciris/shared/   # Shared server resources
    ├── fix_agent_permissions.sh
    └── oauth/            # OAuth configuration files
```

### Communication Flow

1. **Manager → Remote Docker API**: Authenticated via TLS certificates
2. **Deployment**: Manager sends commands to create/start containers remotely
3. **Config Management**: Nginx configs generated locally, deployed via Docker API
4. **File Operations**: Shared files copied once during initialization

## Initial Server Setup

### Prerequisites

- Root SSH access to remote server
- Server has public IP and VPC private IP
- Domain DNS pointing to server's public IP

### Running the Setup Script

The `scripts/setup_remote.sh` script automates the complete server configuration:

```bash
./scripts/setup_remote.sh scoutapi.ciris.ai 10.2.96.4 207.148.14.113
```

Parameters:
- `hostname`: Domain name (e.g., `scoutapi.ciris.ai`)
- `vpc_ip`: Private VPC IP for Docker API (e.g., `10.2.96.4`)
- `public_ip`: Public IP for SSH and HTTPS (e.g., `207.148.14.113`)

### What the Script Does

1. **Docker Installation**
   - Installs Docker CE
   - Installs docker-compose
   - Enables and starts Docker service

2. **User Setup**
   - Creates `ciris` user with UID 1000 (matches container user)
   - Adds user to docker group

3. **Directory Creation**
   ```
   /opt/ciris/
   ├── agents/           # Agent data (uid 1000)
   └── nginx/            # Nginx config (uid 1000)

   /home/ciris/shared/
   ├── oauth/            # OAuth files (uid 1000)
   └── (scripts copied by manager on first connection)

   /etc/ciris-manager/docker-certs/
   └── (TLS certificates)
   ```

4. **TLS Certificate Generation**
   - Creates CA certificate
   - Generates server certificate (with SANs for hostname, VPC IP, public IP)
   - Creates client certificates for manager authentication
   - Secures Docker API with mutual TLS

5. **Docker Daemon Configuration**
   - Configures Docker to listen on VPC IP:2376 with TLS
   - Maintains local socket access
   - Requires client certificate authentication

6. **Firewall Configuration**
   - Opens ports: 22 (SSH), 80 (HTTP), 443 (HTTPS)
   - **Restricts port 2376 to VPC network only** (10.0.0.0/8)
   - Blocks public access to Docker API

7. **SSL Certificate (Let's Encrypt)**
   - Obtains wildcard/domain certificate
   - Configures automatic renewal (twice daily)
   - Sets up renewal hook to reload nginx

8. **Nginx Container Deployment**
   - Deploys `nginx:alpine` container
   - Mounts nginx config directory
   - Mounts Let's Encrypt certificates
   - Starts with `--restart unless-stopped`

9. **OAuth File Transfer**
   - Copies OAuth configuration from main server
   - Sets proper ownership (uid 1000)

10. **Client Certificate Download**
    - Downloads TLS certs to `./docker-certs-{hostname}/`
    - These must be copied to main server for Docker API access

### Post-Setup Configuration

After the script completes, copy certificates to main server:

```bash
# On your local machine (where setup script ran)
scp -r docker-certs-scoutapi.ciris.ai root@agents.ciris.ai:/etc/ciris-manager/docker-certs/

# On main server
chown -R root:root /etc/ciris-manager/docker-certs/scoutapi.ciris.ai
chmod 400 /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/*.pem
```

Add server to `/etc/ciris-manager/config.yml`:

```yaml
servers:
  - server_id: main
    hostname: agents.ciris.ai
    is_local: true

  - server_id: scout
    hostname: scoutapi.ciris.ai
    is_local: false
    vpc_ip: 10.2.96.4
    docker_host: tcp://10.2.96.4:2376
    tls_ca: /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/ca.pem
    tls_cert: /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-cert.pem
    tls_key: /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-key.pem
```

Restart CIRISManager:

```bash
systemctl restart ciris-manager
```

## Directory Structure

### Remote Server Layout

```
/opt/ciris/
├── agents/
│   ├── scout-remote-abc123/          # Agent directory
│   │   ├── data/                     # SQLite database (755, uid 1000)
│   │   ├── data_archive/             # Archived data (755, uid 1000)
│   │   ├── logs/                     # Log files (755, uid 1000)
│   │   ├── config/                   # Agent config (755, uid 1000)
│   │   ├── audit_keys/               # Signing keys (700, uid 1000)
│   │   └── .secrets/                 # Secret storage (700, uid 1000)
│   └── metadata.json                 # Created by manager (NOT synced)
└── nginx/
    ├── nginx.conf                    # Deployed by manager
    └── certs/                        # Optional custom certs

/home/ciris/shared/                   # Server-wide shared resources
├── fix_agent_permissions.sh          # Permission fix script (755, uid 1000)
└── oauth/                            # OAuth configuration (755, uid 1000)
    ├── google_oauth.yml              # OAuth provider config
    ├── credentials.json              # Service account keys
    └── client_secrets.enc            # Encrypted secrets

/etc/docker/certs/                    # Docker TLS certificates
├── ca.pem                            # Certificate Authority
├── server-cert.pem                   # Server certificate
├── server-key.pem                    # Server private key
├── client-cert.pem                   # Client certificate
└── client-key.pem                    # Client private key
```

### Directory Ownership

All agent directories are owned by UID 1000 (ciris user) to match the container user:

- **Agent data directories**: `chown -R 1000:1000`
- **Shared directory**: `chown 1000:1000 /home/ciris/shared`
- **Nginx directory**: `chown -R 1000:1000 /opt/ciris/nginx`

This ensures containers running as UID 1000 can read/write their files without permission issues.

## Shared Files

### Overview

Shared files are resources used by multiple agents on a server. They're copied **once per server** (not per agent) to `/home/ciris/shared/` during manager initialization.

### fix_agent_permissions.sh

**Purpose**: Host-side script that fixes directory permissions after agent creation.

**Location**: `/home/ciris/shared/fix_agent_permissions.sh`

**Source**: `ciris_manager/templates/fix_agent_permissions.sh`

**Deployment**: Automatically copied by manager on first remote server connection

```bash
# Manager initialization (manager.py:__init__)
for server in self.config.servers:
    if not server.is_local:
        self._ensure_remote_server_shared_files(server.server_id)
```

**Usage**: Called once per agent deployment

```bash
/home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/scout-abc123
```

**What it does**:
1. Takes agent path as parameter
2. Recursively sets ownership to 1000:1000
3. Sets directory permissions (755 for most, 700 for sensitive)
4. Ensures all files are readable/writable by container

**Execution method**: Via Docker API exec in nginx container

```python
# Execute via nginx container (has host filesystem access)
nginx_container = docker_client.containers.get("ciris-nginx")
exec_result = nginx_container.exec_run(
    f"sh -c '/home/ciris/shared/fix_agent_permissions.sh {agent_path}'",
    user="root"
)
```

### Why Shared Scripts?

**Benefits**:
- **DRY principle**: One script serves all agents
- **Easy updates**: Update script once, affects all new deployments
- **Reduced redundancy**: No script duplication per agent
- **Centralized maintenance**: Single location for permission logic

**Alternative approaches** (not used):
- ❌ Copy script per agent: Wastes disk space, hard to update
- ❌ Remote execute from main: Requires additional SSH/copying
- ❌ Embed in manager: Requires code push for script changes

## OAuth Configuration

### OAuth File Structure

OAuth configuration files are shared across all agents on a server:

```
/home/ciris/shared/oauth/
├── google_oauth.yml          # OAuth provider configuration
├── credentials.json          # Service account credentials
└── client_secrets.enc        # Encrypted client secrets
```

### OAuth Deployment

**Timing**: OAuth files are copied during initial server setup via `setup_remote.sh`

```bash
# In setup_remote.sh (lines 469-480)
OAUTH_DIR="/home/ciris/shared/oauth"
scp -i "$SSH_KEY" "$OAUTH_DIR"/*.yml "$OAUTH_DIR"/*.json "$OAUTH_DIR"/*.enc \
    root@"$PUBLIC_IP":/home/ciris/shared/oauth/
ssh -i "$SSH_KEY" root@"$PUBLIC_IP" "chown -R 1000:1000 /home/ciris/shared/oauth"
```

**Source**: Main server's `/home/ciris/shared/oauth/`

**Destination**: Remote server's `/home/ciris/shared/oauth/`

**Permissions**: 755, owned by uid 1000

### Agent OAuth Access

Agents access OAuth files via volume mount (configured in docker-compose.yml):

```yaml
volumes:
  - /home/ciris/shared/oauth:/home/ciris/shared/oauth:ro
```

This gives all agents read-only access to shared OAuth configuration without duplicating files.

### OAuth Callback URLs

Each server has its own OAuth callback URL based on hostname:

- **Main server**: `https://agents.ciris.ai/api/{agent_id}/v1/oauth/callback`
- **Scout server**: `https://scoutapi.ciris.ai/api/{agent_id}/v1/oauth/callback`

Set via environment variable:

```python
environment["OAUTH_CALLBACK_BASE_URL"] = f"https://{server_hostname}"
```

## Agent Deployment

### Deployment Flow

When creating an agent on a remote server:

```python
result = await manager.create_agent(
    name="scout-remote",
    template="scout",
    environment={...},
    server_id="scout"  # Target remote server
)
```

### Step-by-Step Process

#### 1. Agent Directory Creation

**Location**: `manager.py:_create_remote_agent_directories()`

```python
await self._create_remote_agent_directories(agent_id, server_id)
```

Creates:
```
/opt/ciris/agents/{agent_id}/
├── data/            (755)
├── data_archive/    (755)
├── logs/            (755)
├── config/          (755)
├── audit_keys/      (700)
└── .secrets/        (700)
```

**Method**: Execute commands via Docker API

```python
# Try nginx container first (best option)
try:
    nginx_container = docker_client.containers.get("ciris-nginx")
    nginx_container.exec_run(f"sh -c 'mkdir -p {dir_path} && chmod {perms} {dir_path}'", user="root")
except:
    # Fallback: Alpine container
    docker_client.containers.run(
        "alpine:latest",
        command=f"sh -c 'mkdir -p {dir_path}'",
        volumes={"/opt/ciris": {"bind": "/opt/ciris", "mode": "rw"}},
        remove=True
    )
```

#### 2. Permission Fix

After creating directories, run shared permission script:

```python
fix_cmd = f"/home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/{agent_id}"
nginx_container.exec_run(f"sh -c '{fix_cmd}'", user="root")
```

This ensures:
- All directories owned by uid 1000
- Correct permissions set (755 or 700)
- No permission issues when container starts

#### 3. Docker Compose Parsing

Parse compose file generated on main server:

```python
with open(compose_path, 'r') as f:
    compose_config = yaml.safe_load(f)

service_config = compose_config['services']['agent']
```

Extract:
- Image name
- Environment variables
- Port mappings
- Volume mounts
- Restart policy

#### 4. Volume Path Translation

Convert local paths to remote paths:

```python
# Local: ./data:/app/data:rw
# Remote: /opt/ciris/agents/{agent_id}/data:/app/data:rw

for volume_str in volumes_config:
    host_path = parts[0]
    if not host_path.startswith("/"):
        # Relative path: ./data
        host_path = f"/opt/ciris/agents/{agent_id}/{host_path.lstrip('./')}"
```

#### 5. Container Creation

Create container via Docker API:

```python
docker_client.containers.run(
    image=image,
    name=f"ciris-{agent_id}",
    environment=environment,
    ports=port_bindings,
    volumes=volumes,
    detach=True,
    restart_policy={"Name": "unless-stopped"}
)
```

#### 6. Nginx Configuration Update

After container starts, update nginx routing:

```python
await self._add_nginx_route(agent_id, port)
```

This triggers a full nginx config regeneration and deployment to all servers.

### Local vs Remote Deployment

|  | Local Server | Remote Server |
|---|---|---|
| **Method** | docker-compose CLI | Docker API |
| **Directory Creation** | Standard filesystem | Docker exec/Alpine containers |
| **Container Start** | `docker-compose up -d` | `docker_client.containers.run()` |
| **Config Files** | Local filesystem | Deployed via Docker API |
| **Permissions** | sudo chown | Permission script via Docker exec |

## Nginx Configuration

### Configuration Generation

Nginx configs are generated **locally** on main server, then deployed to remote servers.

#### Main Server Nginx Update

```python
# Local nginx manager writes directly to file
nginx_manager.update_config(agents)
# File: /home/ciris/nginx/nginx.conf
# Reload: docker exec ciris-nginx nginx -s reload
```

#### Remote Server Nginx Update

```python
# Generate config locally
config_content = nginx_manager.generate_config(agents)

# Deploy to remote via Docker API
docker_client = self.docker_client.get_client(server_id)
success = nginx_manager.deploy_remote_config(
    config_content=config_content,
    docker_client=docker_client,
    container_name="ciris-nginx"
)
```

### Remote Deployment Process

**Method**: Write config via Docker exec in nginx container

```python
def deploy_remote_config(self, config_content: str, docker_client, container_name: str) -> bool:
    # Write to temporary file first
    temp_config = "/tmp/nginx.conf.new"
    write_cmd = f"cat > {temp_config} << 'EOF'\n{config_content}\nEOF"

    container = docker_client.containers.get(container_name)
    container.exec_run(f"sh -c '{write_cmd}'")

    # Validate
    result = container.exec_run(f"nginx -t -c {temp_config}")
    if result.exit_code != 0:
        return False

    # Atomic move
    container.exec_run(f"mv {temp_config} /etc/nginx/nginx.conf")

    # Reload
    container.exec_run("nginx -s reload")
    return True
```

### Why Write Inside Container?

**Benefits**:
- **Atomic updates**: Move is atomic within container filesystem
- **Immediate validation**: Test config before activating
- **No bind mount issues**: Avoids inode changes from external writes
- **Container sees changes**: Docker bind mounts can be cached

**Alternative** (avoided): Write to host file via Alpine container
- Slower (requires container start/stop)
- Harder to validate before activating
- Potential race conditions

### Nginx Config Structure

Remote nginx configs include:

```nginx
http {
    # SSL configuration using Let's Encrypt certs
    ssl_certificate /etc/letsencrypt/live/scoutapi.ciris.ai/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/scoutapi.ciris.ai/privkey.pem;

    # Redirect HTTP to HTTPS
    server {
        listen 80;
        server_name scoutapi.ciris.ai;
        return 301 https://$server_name$request_uri;
    }

    # HTTPS server
    server {
        listen 443 ssl http2;
        server_name scoutapi.ciris.ai;

        # Agent API routes
        location /api/scout-abc123/ {
            proxy_pass http://ciris-scout-abc123:8080/;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

## Permissions Management

### The Permission Challenge

**Problem**: Agent containers run as UID 1000, but directories are initially created by manager operations which may run as different users.

**Solution**: Multi-layered permission handling

### Permission Layers

#### 1. Initial Directory Creation (Remote)

When creating agent directories remotely:

```python
# Create with proper ownership immediately
create_cmd = f"mkdir -p {dir_path} && chmod {perms} {dir_path} && chown 1000:1000 {dir_path}"
```

#### 2. Shared Permission Fix Script

After all directories are created:

```bash
/home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/{agent_id}
```

This script:
- Recursively sets ownership to 1000:1000
- Sets directory permissions (755 or 700)
- Handles all subdirectories and files

#### 3. Container Init Script (Local Agents)

Local agents have `init_permissions.sh` mounted in container:

```yaml
volumes:
  - ./init_permissions.sh:/docker-entrypoint.d/10-fix-permissions.sh:ro
```

Runs **inside container** on startup to fix any permission issues.

### Why Both Scripts?

| Script | Location | Runs | Purpose |
|--------|----------|------|---------|
| `fix_agent_permissions.sh` | `/home/ciris/shared/` | Host (via Docker exec) | One-time fix during agent creation |
| `init_permissions.sh` | Agent directory | Container startup | Local agents, legacy support |

**Remote agents**: Only use `fix_agent_permissions.sh` (no init_permissions.sh mounted)

**Local agents**: Use both (belt and suspenders approach)

### Permission Requirements

```
data/           755 (rwxr-xr-x)  - Database needs broad read
data_archive/   755 (rwxr-xr-x)  - Archived data
logs/           755 (rwxr-xr-x)  - Log files must be readable
config/         755 (rwxr-xr-x)  - Config is not secret
audit_keys/     700 (rwx------)  - Private keys, restrict access
.secrets/       700 (rwx------)  - Secrets storage, maximum security
```

### Debugging Permission Issues

Check ownership on remote server:

```bash
ssh root@scoutapi.ciris.ai "ls -la /opt/ciris/agents/scout-abc123/"
```

Expected output:
```
drwxr-xr-x  ciris ciris  data/
drwx------  ciris ciris  audit_keys/
```

Fix manually if needed:

```bash
ssh root@scoutapi.ciris.ai "/home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/scout-abc123"
```

## Docker API Security

### TLS Mutual Authentication

Remote servers require mutual TLS authentication:

1. **Server Certificate**: Proves server identity to clients
2. **Client Certificate**: Proves client identity to server
3. **CA Certificate**: Validates both server and client certs

### Connection Setup

```python
from docker import DockerClient
import docker.tls as tls

tls_config = tls.TLSConfig(
    client_cert=(cert_path, key_path),
    ca_cert=ca_path,
    verify=True
)

client = DockerClient(
    base_url=f"tcp://{vpc_ip}:2376",
    tls=tls_config
)
```

### Firewall Rules

Port 2376 (Docker API) is **restricted to VPC network only**:

```bash
# UFW rules on remote server
ufw allow from 10.0.0.0/8 to any port 2376 proto tcp
ufw deny 2376/tcp
```

**Important**: Public internet cannot access Docker API, only VPC-connected servers.

### Certificate Locations

**Main Server**:
```
/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/
├── ca.pem              # Certificate Authority
├── client-cert.pem     # Client certificate
└── client-key.pem      # Client private key
```

**Remote Server**:
```
/etc/docker/certs/
├── ca.pem              # Certificate Authority
├── server-cert.pem     # Server certificate
├── server-key.pem      # Server private key
├── client-cert.pem     # For testing
└── client-key.pem      # For testing
```

### Testing Docker API Connection

From main server:

```bash
docker --tlsverify \
    --tlscacert=/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/ca.pem \
    --tlscert=/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-cert.pem \
    --tlskey=/etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-key.pem \
    -H tcp://10.2.96.4:2376 \
    ps
```

Expected: List of containers on remote server

### Security Best Practices

1. **Never expose port 2376 publicly** - VPC only
2. **Rotate certificates annually** - Update TLS certs
3. **Audit API access** - Monitor Docker daemon logs
4. **Use strong key sizes** - 4096-bit RSA minimum
5. **Restrict CA distribution** - Only to authorized servers

## Troubleshooting

### Common Issues

#### 1. Permission Denied Errors

**Symptoms**:
```
Error: EACCES: permission denied, open '/app/data/agent.db'
```

**Diagnosis**:
```bash
ssh root@scoutapi.ciris.ai "ls -la /opt/ciris/agents/scout-abc123/data/"
```

**Fix**:
```bash
ssh root@scoutapi.ciris.ai "/home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/scout-abc123"
docker restart ciris-scout-abc123
```

#### 2. Docker API Connection Failed

**Symptoms**:
```
docker.errors.DockerException: Error while fetching server API version
```

**Diagnosis**:
1. Check firewall: `ssh root@scoutapi.ciris.ai "ufw status"`
2. Verify Docker daemon: `ssh root@scoutapi.ciris.ai "systemctl status docker"`
3. Test from main server (see Testing Docker API Connection above)

**Fix**:
```bash
# Restart Docker daemon
ssh root@scoutapi.ciris.ai "systemctl restart docker"

# Check daemon logs
ssh root@scoutapi.ciris.ai "journalctl -u docker -n 50"
```

#### 3. Nginx Configuration Not Updating

**Symptoms**: Agent created but not accessible via domain

**Diagnosis**:
```bash
# Check nginx container logs
ssh root@scoutapi.ciris.ai "docker logs ciris-nginx"

# Verify config file
ssh root@scoutapi.ciris.ai "docker exec ciris-nginx cat /etc/nginx/nginx.conf | head -50"
```

**Fix**:
```bash
# Force nginx config regeneration from main server
# Via manager API:
curl -X POST http://localhost:8888/manager/v1/nginx/reload

# Or restart manager
systemctl restart ciris-manager
```

#### 4. SSL Certificate Issues

**Symptoms**: HTTPS not working, browser shows certificate errors

**Diagnosis**:
```bash
# Check Let's Encrypt certificate
ssh root@scoutapi.ciris.ai "ls -la /etc/letsencrypt/live/scoutapi.ciris.ai/"

# Verify certificate expiration
ssh root@scoutapi.ciris.ai "openssl x509 -in /etc/letsencrypt/live/scoutapi.ciris.ai/fullchain.pem -noout -dates"
```

**Fix**:
```bash
# Renew certificate manually
ssh root@scoutapi.ciris.ai "certbot renew --force-renewal"

# Reload nginx
ssh root@scoutapi.ciris.ai "docker exec ciris-nginx nginx -s reload"
```

#### 5. Shared Files Not Found

**Symptoms**:
```
/home/ciris/shared/fix_agent_permissions.sh: No such file or directory
```

**Diagnosis**:
```bash
ssh root@scoutapi.ciris.ai "ls -la /home/ciris/shared/"
```

**Fix** (Manual Copy):
```bash
# From main server, copy permission fix script
scp /opt/ciris-manager/ciris_manager/templates/fix_agent_permissions.sh \
    root@scoutapi.ciris.ai:/home/ciris/shared/

ssh root@scoutapi.ciris.ai "chmod 755 /home/ciris/shared/fix_agent_permissions.sh && chown 1000:1000 /home/ciris/shared/fix_agent_permissions.sh"
```

Or trigger automatic sync:
```bash
# Restart manager to trigger shared file sync
systemctl restart ciris-manager
```

### Monitoring

#### Check Remote Server Status

```bash
# From main server
ssh root@scoutapi.ciris.ai "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
```

#### View Agent Logs

```bash
ssh root@scoutapi.ciris.ai "docker logs -f ciris-scout-abc123"
```

#### Check Manager Logs

```bash
# On main server
journalctl -u ciris-manager -f
```

Look for:
- `✅ Docker connection successful: scout`
- `✅ Initialized shared files on scout`
- `✅ Started container ciris-scout-abc123 on remote server scout`

### Getting Help

If issues persist:

1. Check manager logs: `journalctl -u ciris-manager -n 100`
2. Check Docker daemon logs on remote: `ssh root@scoutapi.ciris.ai "journalctl -u docker -n 100"`
3. Verify network connectivity between VPC hosts
4. Review firewall rules on both servers
5. Test Docker API manually (see Testing Docker API Connection)

## Best Practices

1. **One-time setup**: Run `setup_remote.sh` once per server
2. **Centralized management**: All operations via main server
3. **No manual intervention**: Let manager handle deployments
4. **Monitor logs**: Watch for connection issues early
5. **Regular updates**: Keep Docker and certbot updated
6. **Certificate rotation**: Renew before expiration
7. **Backup certificates**: Save TLS certs securely
8. **Document servers**: Keep inventory of remote servers in config.yml

## Summary

Remote server management in CIRISManager provides:

- ✅ Automated server provisioning via `setup_remote.sh`
- ✅ Secure Docker API communication over TLS
- ✅ Centralized agent deployment and configuration
- ✅ Automatic nginx configuration deployment
- ✅ Shared resource management (scripts, OAuth)
- ✅ Robust permission handling
- ✅ SSL certificate automation
- ✅ Horizontal scaling across geographic regions

The system is designed for minimal manual intervention once setup is complete, with all operations orchestrated centrally from the main server.
