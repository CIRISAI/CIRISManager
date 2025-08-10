# Docker Restart Policy and Container Lifecycle Management

## Overview

CIRISManager uses Docker's restart policy strategically to maintain full control over agent container lifecycles while respecting agent autonomy and deployment orchestration requirements.

## Restart Policy: `restart: no`

All CIRIS agent containers are configured with `restart: no` in their docker-compose.yml files.

### Why Not `restart: unless-stopped`?

The previous `restart: unless-stopped` policy had a critical flaw:
- When a container exits (even with code 0 for consensual shutdown), Docker's restart policy always restarts with the **original image** that the container was created with
- This means even after pulling new images, the old image would be used on restart
- The only way to use a new image is to recreate the container entirely

### How `restart: no` Works

With `restart: no`:
- Containers that exit (for any reason) stay stopped
- CIRISManager has full control over when and how to restart containers
- New images are used when containers are recreated after updates

## Container Lifecycle Management

### 1. Deployment Updates (Consensual Shutdown)

When an agent accepts a deployment update:

```
1. Deployment orchestrator pulls new image
2. Sends shutdown request to agent with service token
3. Agent responds HTTP 200 (accept) or 503 (reject)
4. If accepted:
   - Agent exits with code 0 (consensual shutdown)
   - Orchestrator waits for container to stop
   - Orchestrator recreates container with new image
5. If rejected:
   - No action taken, agent continues running
```

**Key Points:**
- Exit code 0 indicates consensual shutdown
- Container is recreated with `docker-compose up -d`
- New image is automatically used
- Respects canary deployment groups

### 2. Crash Recovery (Unexpected Exit)

When an agent crashes unexpectedly:

```
1. Container management loop checks every 30 seconds
2. Finds containers with status "exited"
3. Checks exit code:
   - Code 0: Consensual shutdown, do NOT restart
   - Non-zero: Crash, proceed with recovery
4. Checks if part of recent deployment (< 5 minutes):
   - Yes: Skip (deployment orchestrator handles it)
   - No: Restart with docker-compose up -d
```

**Key Points:**
- Only restarts crashed containers (non-zero exit)
- Never restarts consensual shutdowns (exit code 0)
- Never touches running containers (maintains autonomy)
- Avoids interfering with active deployments

### 3. Agent Autonomy

The system maintains agent autonomy by:

1. **Never forcing restarts on running containers**
   - Running agents are never touched
   - Agents control their own lifecycle while running

2. **Respecting shutdown decisions**
   - Agents can reject update requests (HTTP 503)
   - Rejected updates are not retried immediately
   - Agents remain in control of when to update

3. **Exit code semantics**
   - Exit 0: Agent chose to shutdown (respected)
   - Non-zero: Unexpected crash (recovered)

## Expected Behavior Examples

### Example 1: Successful Update

```
Agent: datum-abc123
Status: Running v1.3.3
Action: CD update to v1.3.4 available

1. Manager pulls v1.3.4 image
2. Manager sends shutdown request
3. Agent accepts (HTTP 200)
4. Agent exits cleanly (code 0)
5. Manager waits for container stop
6. Manager runs: docker-compose up -d
7. Container starts with v1.3.4 image
```

### Example 2: Busy Agent Rejects Update

```
Agent: datum-xyz789
Status: Running v1.3.3, processing user request
Action: CD update to v1.3.4 available

1. Manager pulls v1.3.4 image
2. Manager sends shutdown request
3. Agent rejects (HTTP 503 - busy)
4. Manager logs rejection
5. Agent continues running v1.3.3
6. Update retried later or manually
```

### Example 3: Agent Crash Recovery

```
Agent: datum-def456
Status: Crashed (segfault, exit code 139)
Action: Crash recovery

1. Container management loop detects exit code 139
2. Checks if stopped > 5 minutes ago (not deployment)
3. Runs: docker-compose up -d
4. Container restarts with same image
5. Agent resumes operation
```

### Example 4: Consensual Shutdown Not Restarted

```
Agent: datum-ghi789
Status: User requested shutdown
Action: None

1. User requests shutdown via API
2. Agent exits cleanly (code 0)
3. Container management loop detects exit code 0
4. Recognizes consensual shutdown
5. Does NOT restart container
6. Container remains stopped until manually started
```

## Configuration

### Docker Compose Generation

The `compose_generator.py` creates docker-compose.yml with:

```yaml
services:
  agent-id:
    restart: "no"  # Changed from "unless-stopped"
    # ... other configuration
```

### Container Management Settings

In `/etc/ciris-manager/config.yml`:

```yaml
container_management:
  crash_check_interval: 30  # Check for crashes every 30 seconds
  deployment_grace_period: 300  # 5 minutes grace for deployments
```

## Testing

The system includes comprehensive tests for:

1. **Crash recovery**: Containers with non-zero exit codes are restarted
2. **Consensual shutdown**: Exit code 0 containers are not restarted
3. **Running containers**: Never touched (autonomy maintained)
4. **Recent stops**: Containers stopped < 5 minutes ago are skipped
5. **Old crashes**: Containers crashed > 5 minutes ago are restarted
6. **Deployment integration**: Orchestrator recreates after successful shutdown

## Migration Guide

For existing deployments:

1. **Update CIRISManager** to latest version with new restart policy
2. **Regenerate docker-compose files** for all agents:
   ```bash
   ciris-manager regenerate-compose --all
   ```
3. **Recreate containers** to apply new policy:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

## Troubleshooting

### Container not updating after deployment

**Symptom**: Agent accepts shutdown but restarts with old version

**Cause**: Using `restart: unless-stopped` policy

**Fix**: 
1. Update docker-compose.yml to use `restart: no`
2. Recreate container: `docker-compose up -d --force-recreate`

### Container not restarting after crash

**Symptom**: Crashed container stays down

**Check**:
1. Verify exit code: `docker inspect <container> --format='{{.State.ExitCode}}'`
2. Check if exit code is 0 (consensual) or non-zero (crash)
3. Check container management logs: `journalctl -u ciris-manager | grep crash`

### Container restarting when it shouldn't

**Symptom**: Container with exit code 0 gets restarted

**This should not happen** with current implementation. If it does:
1. Check CIRISManager version is latest
2. Verify docker-compose.yml has `restart: no`
3. Check for external automation tools

## Design Rationale

### Why This Approach?

1. **Predictable Updates**: New images are guaranteed to be used after updates
2. **Respect Autonomy**: Agents control when they update
3. **Crash Recovery**: Genuine crashes are recovered automatically
4. **Clean Separation**: Deployment updates vs crash recovery are distinct
5. **Canary Safety**: Deployment groups are strictly respected

### Alternative Approaches Considered

1. **Docker Swarm/Kubernetes**: Too complex for current needs
2. **Custom restart policy**: Docker doesn't support custom policies
3. **Always recreate**: Would bypass agent consent
4. **No automatic recovery**: Would leave crashed agents down

## Summary

The `restart: no` policy combined with CIRISManager's lifecycle management provides:

- ✅ Reliable updates with new images
- ✅ Respect for agent autonomy
- ✅ Automatic crash recovery
- ✅ Clean deployment orchestration
- ✅ No interference with running containers
- ✅ Clear exit code semantics

This design ensures that agents are updated only when they consent, crashes are recovered automatically, and the system maintains predictable behavior throughout the container lifecycle.