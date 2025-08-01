# CD Orchestration

CIRISManager orchestrates agent deployments with informed consent.

## Endpoints

### `POST /manager/v1/updates/notify`
Notifies agents of available updates with context.

**Request**:
```json
{
  "agent_image": "ghcr.io/cirisai/ciris-agent:latest",
  "strategy": "canary",
  "changelog": "fix: memory leak in telemetry service",
  "risk_level": "low",
  "commit_sha": "abc123",
  "version": "1.2.3"
}
```

### `GET /manager/v1/updates/status`
Returns current deployment status.

### `GET /manager/v1/updates/latest/changelog`
Returns recent commits for agent context.

## Agent Notification

Agents receive:
```json
{
  "new_image": "ghcr.io/cirisai/ciris-agent:latest",
  "changelog": "fix: memory leak in telemetry service",
  "risk_level": "low",
  "peer_results": "3/3 peers updated successfully",
  "version": "1.2.3"
}
```

Agents respond with:
- `TASK_COMPLETE` - Accept update
- `DEFER` - Try again later
- `REJECT` - Decline update

## Setup

1. Set `CIRIS_DEPLOY_TOKEN` environment variable
2. Add `DEPLOY_TOKEN` secret to GitHub repository
3. Update workflow to include changelog and risk assessment