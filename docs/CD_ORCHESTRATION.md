# CD Orchestration with CIRISManager

CIRISManager provides centralized deployment orchestration for the CIRIS agent fleet, enabling safe and controlled updates while respecting agent autonomy.

## Overview

The CD system follows a clean separation of concerns:

1. **GitHub Actions** - Builds containers and notifies CIRISManager
2. **CIRISManager** - Orchestrates deployment based on strategy
3. **CIRIS Agents** - Autonomously decide whether to accept updates

## Architecture

```
┌─────────────────┐
│  GitHub Actions │
│   (CIRISAgent)  │
└────────┬────────┘
         │ POST /manager/v1/updates/notify
         │ (with DEPLOY_TOKEN)
         ▼
┌─────────────────┐
│  CIRISManager   │──────┬──────┬──────┐
│  (Orchestrator) │      │      │      │
└─────────────────┘      ▼      ▼      ▼
                    Agent-1  Agent-2  Agent-N
                    (decide) (decide) (decide)
```

## API Endpoints

### Notify Update
`POST /manager/v1/updates/notify`

Receives deployment notifications from CD pipeline.

**Authentication**: Bearer token (DEPLOY_TOKEN)

**Request Body**:
```json
{
  "agent_image": "ghcr.io/cirisai/ciris-agent:latest",
  "gui_image": "ghcr.io/cirisai/ciris-gui:latest",
  "strategy": "canary",  // or "immediate", "manual"
  "source": "github-actions",
  "commit_sha": "abc123...",
  "message": "Optional deployment message",
  "metadata": {
    "version": "2.0.0",
    "pr_number": 123
  }
}
```

**Response**:
```json
{
  "deployment_id": "deploy-20250801-123456",
  "status": "in_progress",
  "agents_total": 10,
  "agents_updated": 0,
  "agents_deferred": 0,
  "agents_rejected": 0,
  "started_at": "2025-08-01T12:00:00Z",
  "canary_phase": "explorers",
  "message": "Deployment started"
}
```

### Check Status
`GET /manager/v1/updates/status`

Get deployment status.

**Authentication**: Bearer token (DEPLOY_TOKEN)

**Query Parameters**:
- `deployment_id` (optional) - Specific deployment ID, or current if omitted

**Response**: Same as notify response with updated counts

## Deployment Strategies

### Canary Deployment
Progressive rollout through agent personality groups:

1. **Explorers** (10%) - Early adopters, willing to try new things
2. **Early Adopters** (30%) - Innovation enthusiasts
3. **Pragmatists** (40%) - Want proven stability
4. **Conservatives** (20%) - Maximum stability preference

```yaml
strategy: canary
canary_config:
  wait_between_phases: 3600  # 1 hour
  success_threshold: 0.8     # 80% must succeed
```

### Immediate Deployment
All agents notified simultaneously (emergency patches).

```yaml
strategy: immediate
```

### Manual Deployment
No automatic notifications, admin triggers via UI.

```yaml
strategy: manual
```

## Authentication

CD endpoints require Bearer token authentication:

```bash
curl -X POST https://agents.ciris.ai/manager/v1/updates/notify \
  -H "Authorization: Bearer ${DEPLOY_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"agent_image": "...", "strategy": "canary"}'
```

The token is stored as:
- GitHub Secret: `DEPLOY_TOKEN` in CIRISAgent repo
- Environment Variable: `CIRIS_DEPLOY_TOKEN` in CIRISManager

## Agent Response Protocol

When notified of an update, agents process it as a task and can respond:

- **TASK_COMPLETE** - Accept update and gracefully shutdown
- **DEFER** - Delay update (busy with critical task)
- **REJECT** - Refuse update (e.g., incompatible version)

CIRISManager respects these decisions and tracks them in deployment status.

## Setup Instructions

### 1. Generate Deployment Token

```bash
# Generate secure token
openssl rand -hex 32
```

### 2. Add to GitHub Secrets

In CIRISAgent repository:
```bash
gh secret set DEPLOY_TOKEN --body "your-generated-token"
```

### 3. Configure CIRISManager

Set environment variable:
```bash
echo "CIRIS_DEPLOY_TOKEN=your-generated-token" >> /etc/ciris-manager/environment
systemctl restart ciris-manager-api
```

### 4. Update GitHub Workflow

```yaml
- name: Notify CIRISManager
  run: |
    curl -X POST https://agents.ciris.ai/manager/v1/updates/notify \
      -H "Authorization: Bearer ${{ secrets.DEPLOY_TOKEN }}" \
      -H "Content-Type: application/json" \
      -d '{
        "agent_image": "ghcr.io/cirisai/ciris-agent:latest",
        "gui_image": "ghcr.io/cirisai/ciris-gui:latest",
        "strategy": "canary",
        "source": "github-actions",
        "commit_sha": "${{ github.sha }}"
      }'
```

## Monitoring Deployments

### Via API
```bash
# Get current deployment
curl -H "Authorization: Bearer ${DEPLOY_TOKEN}" \
  https://agents.ciris.ai/manager/v1/updates/status

# Get specific deployment
curl -H "Authorization: Bearer ${DEPLOY_TOKEN}" \
  https://agents.ciris.ai/manager/v1/updates/status?deployment_id=deploy-123
```

### Via Logs
```bash
# CIRISManager logs
journalctl -u ciris-manager-api -f | grep deployment

# Agent responses
docker logs ciris-agent-datum | grep "update notification"
```

## Security Considerations

1. **Token Rotation** - Rotate DEPLOY_TOKEN periodically
2. **HTTPS Only** - Never send tokens over HTTP
3. **Audit Logging** - All deployments are logged
4. **Rate Limiting** - Prevents deployment spam
5. **Agent Autonomy** - Agents can always refuse updates

## Troubleshooting

### Deployment Not Starting
- Check token authentication: `curl -I -H "Authorization: Bearer $TOKEN" .../status`
- Verify CIRISManager logs: `journalctl -u ciris-manager-api -n 100`
- Check for existing deployment: Only one active deployment allowed

### Agents Not Updating
- Check agent logs for update notifications
- Verify agent health endpoint is responding
- Check network connectivity between Manager and agents
- Review agent's decision (accept/defer/reject)

### Token Issues
- Ensure token matches in both GitHub and CIRISManager
- Check for extra whitespace in environment variable
- Verify Bearer format: `Authorization: Bearer <token>`

## Best Practices

1. **Test in Staging** - Always test deployment strategies in non-production first
2. **Monitor Canary Phases** - Watch early phases before proceeding
3. **Respect Agent Decisions** - Don't force updates on agents that defer
4. **Document Deployments** - Include meaningful messages and metadata
5. **Plan Rollbacks** - Know how to revert if issues arise

## Future Enhancements

- [ ] Rollback support with automatic reversion
- [ ] Deployment scheduling and maintenance windows
- [ ] Multi-region deployment coordination
- [ ] A/B testing support for agent features
- [ ] Integration with monitoring systems (Prometheus/Grafana)