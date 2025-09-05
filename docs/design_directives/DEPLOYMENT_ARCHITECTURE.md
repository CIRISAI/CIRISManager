## **name: "🏗️ Architecture Directive" title: "🏗️ [ARCHITECTURE]: Beta Deployment Architecture" labels: ["architecture", "deployment", "beta"] assignees: ''**

### **1. Objective**

To establish a clear, coherent deployment architecture for the CIRIS platform with four distinct components: CIRISManager (orchestration layer), nginx (routing layer), CIRISGUI (interface layer), and CIRIS Agents (execution layer). This directive clarifies the production deployment model for beta release, establishing that CIRISManager will eventually have full lifecycle control over all containerized components through its management API.

### **2. Functional Requirements**

#### **2.1 Component Deployment**

* **CIRISManager** SHALL deploy as a systemd service on the host (NOT as a container) to maintain privileged access to Docker socket for orchestrating all other components.
* **Nginx** SHALL deploy as a Docker container (`ciris-nginx`) to handle all inbound HTTPS traffic and route requests to appropriate services.
* **CIRISGUI** SHALL deploy as a Docker container (`ciris-gui`) using the frontend from the CIRISAgent repository.
* **CIRIS Agents** SHALL deploy as individual Docker containers using `ghcr.io/cirisai/ciris-agent:latest` as the base image.

#### **2.2 Orchestration Control**

* CIRISManager SHALL have full lifecycle control over all three containerized components (nginx, GUI, agents) through its management API.
* The Manager SHALL monitor all containers and automatically generate nginx reverse proxy configurations when components are added, removed, or modified.
* The nginx container SHALL automatically reload configurations when CIRISManager updates routing rules in the mounted volume.
* All containers SHALL be defined in a centralized docker-compose.yml file located at `/opt/ciris/docker-compose.yml`.

#### **2.3 Separation of Concerns**

* **CIRISManager**: Container lifecycle management, health monitoring, nginx config generation, orchestration API
* **Nginx**: SSL termination, request routing, load balancing
* **CIRISGUI**: Web interface for agent interaction and management
* **Agents**: Business logic execution, API endpoints, user interactions

### **3. Success Criteria**

* **Given** a new agent definition in docker-compose.yml, **When** `docker-compose up -d ciris-agent-{name}` is executed, **Then** CIRISManager shall detect the new container within 30 seconds and generate appropriate nginx routing configuration.
* **Given** an HTTPS request to `https://domain.com/agent/{name}/api/v1/*`, **When** the corresponding agent container is healthy, **Then** nginx shall route the request to the correct agent container port.
* **Given** an agent container crashes 3 times in 5 minutes, **When** the watchdog detects this pattern, **Then** CIRISManager shall stop attempting restarts and mark the agent as in crash loop.
* **Given** the nginx configuration directory is mounted at `/opt/ciris/nginx/`, **When** CIRISManager writes a new configuration file, **Then** the nginx container shall reload within 10 seconds.
* **Given** a request to `/manager/v1/*`, **When** received by nginx, **Then** it shall be proxied to the CIRISManager API on port 8888.

### **4. Implementation Details**

#### Directory Structure
```
/opt/ciris/
├── docker-compose.yml   # Defines all agent containers and nginx
├── agents/              # Agent-specific data and metadata
│   └── {agent-name}/    # Per-agent directory
├── nginx/               # Active nginx configurations
│   ├── 00-manager.conf  # Manager routing (static)
│   ├── 01-gui.conf      # GUI routing (static)
│   └── 10-agent-*.conf  # Agent routing (dynamic)
└── nginx-new/           # Staging area for config updates

/opt/ciris-manager/      # CIRISManager installation
├── venv/                # Python virtual environment
└── config.yml           # Manager configuration
```

#### Network Architecture
```
┌─────────────────────────────────────────────────┐
│                   INTERNET                       │
└─────────────────────────────────────────────────┘
                        │
                   HTTPS:443
                        │
    ┌───────────────────┴───────────────────────┐
    │            ciris-nginx                     │
    │         (Docker Container)                 │
    │   - SSL: /etc/letsencrypt                  │
    │   - Configs: /opt/ciris/nginx (mounted)    │
    └───────────────────┬───────────────────────┘
                        │
        ┌───────────────┼───────────────────────┐
        ↓               ↓                       ↓
  /manager/v1/*        /                   /agent/{name}/*
        │               │                       │
┌───────┴──────┐ ┌─────┴──────┐ ┌─────────────┴──────────┐
│ CIRISManager │ │  CIRISGUI  │ │     CIRIS Agents       │
│   :8888      │ │   :3000    │ │      :8080-8099        │
│  (systemd)   │ │  (docker)  │ │      (docker)          │
│              │ │            │ │ image: ciris-agent:latest│
└──────┬───────┘ └────────────┘ └──────────────────────┘
       │                                   ↑
       └────────── orchestrates ───────────┘
                  all containers
```

#### Agent Deployment Workflow

1. **Prepare Agent Environment**
   ```bash
   # Create agent-specific .env file
   cat > /opt/ciris/.env.agent-{name} <<EOF
   CIRIS_AGENT_NAME={name}
   CIRIS_API_PORT={allocated-port}
   OPENAI_API_KEY={key}
   # Additional agent-specific variables
   EOF
   ```

2. **Add Agent to Docker Compose**
   ```yaml
   # In /opt/ciris/docker-compose.yml
   services:
     ciris-agent-{name}:
       image: ghcr.io/cirisai/ciris-agent:latest
       container_name: ciris-agent-{name}
       env_file: .env.agent-{name}
       ports:
         - "127.0.0.1:{port}:{port}"
       volumes:
         - ./agents/{name}:/app/data
       networks:
         - ciris-network
       labels:
         - "ciris.agent.name={name}"
         - "ciris.agent.port={port}"
   ```

3. **Deploy Agent**
   ```bash
   cd /opt/ciris
   docker-compose up -d ciris-agent-{name}
   ```

4. **Automatic Detection and Routing**
   * CIRISManager detects new container via Docker API
   * Reads labels to determine agent name and port
   * Generates `/opt/ciris/nginx/10-agent-{name}.conf`
   * Nginx container detects file change and reloads

### **5. Configuration Schema**

#### CIRISManager Configuration (`/opt/ciris-manager/config.yml`)
```yaml
docker:
  compose_file: /opt/ciris/docker-compose.yml
  socket: /var/run/docker.sock

nginx:
  config_dir: /opt/ciris/nginx
  staging_dir: /opt/ciris/nginx-new
  reload_delay: 5  # seconds

api:
  host: 0.0.0.0
  port: 8888

manager:
  agents_dir: /opt/ciris/agents
  port_range: [8080, 8099]
```

#### Nginx Routing Template
```nginx
# Generated by CIRISManager
# /opt/ciris/nginx/10-agent-{name}.conf

location /agent/{name}/ {
    proxy_pass http://ciris-agent-{name}:{port}/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Agent-Name {name};
}
```

### **6. Security Considerations**

* CIRISManager runs as systemd service with specific user/group permissions
* Docker socket access limited to ciris-manager user
* Agent containers run with minimal privileges
* Inter-container communication restricted to ciris-network
* SSL certificates mounted read-only in nginx container
* Agent data directories have restricted permissions

### **7. Migration Path**

For existing deployments:
1. Stop existing nginx if running on host
2. Deploy nginx container with mounted config directory
3. Ensure CIRISManager has write access to nginx config directory
4. Update agent containers to use standardized naming convention
5. Verify routing through nginx container

### **8. Future Considerations**

* Multi-host deployment with container orchestration (Kubernetes/Swarm)
* High availability with multiple nginx instances
* Centralized logging and metrics collection
* Dynamic SSL certificate management for agent-specific domains
* WebSocket support for real-time agent communication
* Full container lifecycle management through Manager API (start/stop/restart all components)
* Automated health checks and recovery for all four components
* Version coordination between CIRISManager and container images
