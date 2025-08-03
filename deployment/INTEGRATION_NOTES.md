# CIRISManager Integration Notes

## Critical Integration Points with CIRISAgent

### Architecture Overview
```
Browser → Nginx (port 80/443) → Routes:
  - /manager/v1/*      → CIRISManager (port 8888)
  - /v1/*              → Default agent (Datum)
  - /api/{agent}/v1/*  → Specific agents
  - /                  → GUI (port 3000)
```

### Key Facts
1. **CIRISManager is the Orchestrator**
   - Discovers all agents via Docker labels
   - Generates complete nginx configuration
   - Manages all routing dynamically

2. **Port Configuration**
   - CIRISManager: 8888 (not 9000)
   - GUI: 3000
   - Agents: Dynamically allocated (8000-8999)

3. **Client Code Resilience**
   - Uses `window.location.origin/manager/v1/*` pattern
   - Falls back gracefully when manager unavailable
   - No hardcoded URLs or dependencies

### Required Setup

1. **CIRISManager must be running on port 8888**
   ```bash
   systemctl start ciris-manager-api
   ```

2. **Nginx configuration managed by CIRISManager**
   - Do NOT manually edit nginx configs for agents
   - CIRISManager will regenerate them

3. **Same-host requirement**
   - All services must run on same host
   - Uses `host.docker.internal` for container→host communication

### Deployment Checklist

- [ ] CIRISManager running on port 8888
- [ ] Nginx enabled in CIRISManager config
- [ ] GUI container accessible on port 3000
- [ ] Docker socket accessible to CIRISManager
- [ ] Nginx service running and configured

### Common Integration Issues

1. **"Manager unavailable" in GUI**
   - Check: Is CIRISManager API running on 8888?
   - Check: Is nginx routing /manager/v1/* correctly?

2. **Agents not appearing in GUI**
   - Check: Docker labels on agent containers
   - Check: CIRISManager logs for discovery errors

3. **Routing errors**
   - Check: `/etc/nginx/ciris-agents/` for generated configs
   - Run: `nginx -t` to validate configuration

4. **OAuth "404 Not Found" after Google login**
   - Cause: Missing nginx route for `/manager/oauth/callback`
   - Fix: Add location block to existing nginx config:
   ```nginx
   location /manager/oauth/callback {
       proxy_pass http://ciris_manager;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

5. **"attempt to write a readonly database"**
   - Cause: systemd ProtectSystem=strict blocking writes
   - Fix: Add `/var/lib/ciris-manager` to ReadWritePaths in service file

### Testing Integration

```bash
# 1. Test manager API directly
curl http://localhost:8888/manager/v1/health

# 2. Test through nginx
curl https://your-domain/manager/v1/health

# 3. Test agent discovery
curl https://your-domain/manager/v1/agents

# 4. Check nginx config generation
ls -la /etc/nginx/ciris-agents/
```

### The Magic

CIRISManager's `nginx_manager.py` automatically:
- Discovers new agents
- Allocates unique ports
- Generates nginx routes
- Reloads nginx configuration
- Updates GUI with agent info

This means you just need to:
1. Deploy CIRISManager
2. Start agents with proper labels
3. Everything else is automatic!
