# CD Orchestration

CIRISManager orchestrates agent deployments with secure authentication and comprehensive audit logging.

## Endpoints

### `POST /manager/v1/updates/notify`
Notifies agents of available updates with context.

**Request**:
```json
{
  "agent_image": "ghcr.io/cirisai/ciris-agent:latest",
  "gui_image": "ghcr.io/cirisai/ciris-gui:latest",
  "strategy": "canary",
  "changelog": "fix: memory leak in telemetry service\nfeat: add new monitoring endpoint\ntest: improve coverage",
  "risk_level": "low",
  "commit_sha": "abc123",
  "version": "1.2.3"
}
```

**Note**: The `changelog` field should contain ALL commit messages from the release, separated by newlines. These will be formatted as bullet points in the shutdown message sent to agents.

### `GET /manager/v1/updates/status`
Returns current deployment status.

### `GET /manager/v1/updates/latest/changelog`
Returns recent commits for agent context.

## Agent Update Process

The manager triggers agent updates by calling the agent's shutdown endpoint:

### `POST /v1/system/shutdown`
**Payload**:
```json
{
  "reason": "System shutdown requested: Runtime: CD update to version v1.2.3 (deployment abc123)\nRelease notes:\n  • fix: memory leak in telemetry service\n  • feat: add new monitoring endpoint\n  • test: improve coverage\n(API shutdown by wa-system-admin)",
  "force": false,
  "confirm": true
}
```

**Shutdown Reason Format**:
- For semantic versions: `CD update to version v1.2.3`
- For commit SHAs: `CD update to commit abc123`
- Includes full changelog as formatted bullet points when available
- Always prefixed with `System shutdown requested: Runtime:`
- Always suffixed with `(API shutdown by wa-system-admin)`

**Authentication**: Uses secure service tokens (see Security section below)

**Agent Response**:
- HTTP 200: Agent accepts shutdown for update
- HTTP 503 or other non-200: Agent rejects shutdown at this time

Docker's restart policy (`restart: unless-stopped`) automatically brings up the updated container.

## Security

### Service Token Authentication
Each agent has a unique service token for manager-to-agent communication:
- Tokens are 256-bit cryptographically secure random values
- Stored encrypted at rest using Fernet symmetric encryption
- Transmitted as `Authorization: Bearer service:{token}`
- Audit logged for compliance tracking

### Encryption Configuration
- Set `CIRIS_ENCRYPTION_KEY` for production (base64 Fernet key)
- Falls back to deriving key from `MANAGER_JWT_SECRET` if not set
- Tokens encrypted in agent registry metadata

### Audit Logging
All deployment actions are logged to `/var/log/ciris-manager/security-audit.log`:
- Service token usage with hashed token ID
- Deployment lifecycle events (start, phases, completion)
- Agent update decisions (accept, reject)
- Errors and exceptions with context

## Setup

1. Set environment variables:
   - `CIRIS_DEPLOY_TOKEN` - For CD webhook authentication
   - `CIRIS_ENCRYPTION_KEY` - For token encryption (production)
   - `MANAGER_JWT_SECRET` - Fallback for encryption key derivation

2. Add `DEPLOY_TOKEN` secret to GitHub repository

3. Update workflow to include changelog and risk assessment

## Implementation Notes for CIRISAgent

**IMPORTANT**: CIRISAgent needs to implement the following to support secure deployments:

1. **Service Token Authentication**:
   - Accept `Authorization: Bearer service:{token}` headers
   - Validate token from `CIRIS_SERVICE_TOKEN` environment variable
   - Use constant-time comparison to prevent timing attacks
   - Return 401 for invalid tokens

2. **Shutdown Endpoint Enhancement**:
   - `/v1/system/shutdown` should check if agent can safely shutdown
   - Return HTTP 200 if shutdown is acceptable
   - Return HTTP 503 if agent is busy and cannot shutdown
   - Include meaningful error messages in response body

3. **Example Implementation**:
```python
# In agent's auth middleware
if auth_header.startswith("Bearer service:"):
    provided_token = auth_header[len("Bearer service:"):]
    expected_token = os.getenv("CIRIS_SERVICE_TOKEN")
    if not expected_token or not constant_time_compare(provided_token, expected_token):
        return Response(status_code=401, content="Invalid service token")

# In shutdown endpoint
@app.post("/v1/system/shutdown")
async def shutdown(request: ShutdownRequest, auth: ServiceAuth = Depends(verify_service_token)):
    if agent.is_processing_critical_task():
        return Response(
            status_code=503,
            content="Agent is processing critical task, cannot shutdown now"
        )
    
    # Initiate graceful shutdown
    asyncio.create_task(graceful_shutdown(request.reason))
    return {"status": "shutdown initiated"}
```