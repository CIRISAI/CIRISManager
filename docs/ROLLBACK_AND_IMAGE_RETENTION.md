# Rollback and Image Retention System

## Overview

CIRISManager implements a human-in-the-loop rollback system that respects agent autonomy while ensuring system stability. When agents fail to reach operational state, the system proposes rollback to human operators rather than automatically reverting.

## Key Principles

### 1. Agent Autonomy Respected
- **No automatic rollback** - Agents cannot consent when non-operational
- **Human decision required** - Operator must approve rollback proposals
- **Deferred updates honored** - Agent deferrals are not treated as failures

### 2. Image Version Retention (N-2 Policy)
The system maintains three versions of each image:
- **Current** - Active version in production
- **N-1** - Previous stable version (primary rollback target)
- **N-2** - Two versions back (emergency fallback)

Older versions are automatically cleaned up to prevent disk space issues.

## Rollback Triggers

### Automatic Proposals
Rollback is **proposed** (not executed) when:

1. **Failure to reach WORK state**
   - Agent doesn't reach WORK cognitive state within 5 minutes
   - Applies during canary deployment phases

2. **Crash loop detection**
   - Agent crashes 3+ times within 5 minutes
   - Monitored by watchdog service

3. **Critical incidents**
   - High severity incidents detected during stability period
   - Checked via telemetry API

### Manual Rollback
Operators can initiate rollback at any time through:
- Manager UI rollback button
- API endpoint: `POST /manager/v1/updates/rollback`

## Rollback Mechanism

### How It Works
1. **Container restart with previous image**
   - Docker Compose `restart: unless-stopped` policy utilized
   - Container stopped and restarted with N-1 image

2. **Image pinning via digests**
   - Exact versions tracked using SHA256 digests
   - Ensures deterministic rollback to known-good state

3. **Metadata updates**
   - Agent registry updated with rollback status
   - Version history maintained for audit trail

### Technical Implementation

```python
# Rollback process for non-operational agents
async def _rollback_agents(deployment):
    for agent_id in affected_agents:
        # Get N-1 version from metadata
        n1_image = agent.metadata["previous_images"]["n-1"]
        
        # Stop failed container
        docker stop <container>
        
        # Restart with N-1 image
        docker run -d --restart unless-stopped <n1_image>
        
        # Update metadata
        agent.metadata["current_images"]["agent"] = n1_image
```

## Version History Tracking

### Metadata Structure
Each agent maintains version history in its metadata:

```json
{
  "current_images": {
    "agent": "sha256:abc123...",
    "agent_tag": "ghcr.io/cirisai/ciris-agent:v1.4.0"
  },
  "previous_images": {
    "n-1": "sha256:def456...",
    "n-2": "sha256:ghi789..."
  },
  "version_history": [
    {
      "timestamp": "2025-08-12T10:00:00Z",
      "agent_image": "ghcr.io/cirisai/ciris-agent:v1.4.0",
      "deployment_id": "deploy-123"
    }
  ]
}
```

### Version Rotation
On successful deployment:
1. Current → N-1
2. N-1 → N-2
3. N-2 → Removed (image cleanup)
4. New version → Current

## API Endpoints

### Get Rollback Proposals
```http
GET /manager/v1/updates/rollback-proposals
```
Returns active rollback proposals requiring operator decision.

### Approve Rollback
```http
POST /manager/v1/updates/approve-rollback
{
  "deployment_id": "deploy-123"
}
```
Executes approved rollback to N-1 version.

### Manual Rollback
```http
POST /manager/v1/updates/rollback
{
  "deployment_id": "deploy-123"
}
```
Initiates rollback for completed deployment.

## UI Integration

### Rollback Proposal Display
When rollback is proposed:
1. **Alert banner** appears in Manager UI
2. **Reason displayed** (e.g., "No agents reached WORK state")
3. **Affected agents listed** with current/target versions
4. **Action buttons**: Approve Rollback / Dismiss

### Deployment Status
- `rollback_proposed` - Awaiting operator decision
- `rolling_back` - Rollback in progress
- `rolled_back` - Successfully reverted
- `rollback_failed` - Rollback encountered errors

## Audit Trail

All rollback actions are logged to `/var/log/ciris-manager/audit.jsonl`:

```json
{
  "timestamp": "2025-08-12T10:15:00Z",
  "action": "rollback_proposed",
  "deployment_id": "deploy-123",
  "user": "system",
  "details": {
    "reason": "No explorer agents reached WORK state within 5 minutes",
    "affected_agents": 2
  }
}
```

## Best Practices

### For Operators
1. **Investigate before approving** - Check agent logs for root cause
2. **Consider waiting** - Agents may recover given more time
3. **Document decisions** - Add notes when approving/rejecting rollback

### For Deployments
1. **Test in canary groups** - Catch issues before general rollout
2. **Monitor WORK state** - Key indicator of agent health
3. **Keep N-1 stable** - Ensure fallback version is known-good

## Integration with Image Cleanup

The `DockerImageCleanup` service automatically:
- Runs after successful deployments
- Keeps exactly 3 versions (current, N-1, N-2)
- Removes dangling images
- Preserves images in active use

Configuration:
```python
cleanup = DockerImageCleanup(versions_to_keep=3)
```

## Failure Scenarios

### Agent Cannot Start
- **Cause**: Image corrupted or missing dependencies
- **Resolution**: Rollback to N-1, investigate image build

### Agent Starts but Crashes
- **Cause**: Runtime errors, resource constraints
- **Resolution**: Check logs, may need config adjustment

### Agent Defers Update
- **Cause**: Agent actively working, not ready for update
- **Resolution**: No action needed, retry later

### N-1 Also Fails
- **Cause**: Regression introduced earlier
- **Resolution**: Manual intervention, possibly rollback to N-2

## Security Considerations

1. **Rollback requires authentication** - Manager token required
2. **Audit logging** - All actions tracked for compliance
3. **Version integrity** - SHA256 digests ensure exact versions
4. **No auto-rollback** - Human judgment required for safety

## Future Enhancements

1. **Automated rollback approval** for specific failure patterns
2. **Rollback testing** in staging environment
3. **Version compatibility matrix** for multi-agent systems
4. **Rollback metrics dashboard** for trend analysis