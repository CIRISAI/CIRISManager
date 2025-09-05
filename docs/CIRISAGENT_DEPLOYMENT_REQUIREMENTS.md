# CIRISAgent Deployment Requirements

This document specifies **exactly** what CIRISAgent needs to implement to support secure deployments orchestrated by CIRISManager.

## 1. Service Token Authentication

### Environment Variable
Each agent receives a unique `CIRIS_SERVICE_TOKEN` environment variable from CIRISManager when created.

### Authentication Header Format
```
Authorization: Bearer service:{token}
```

### Implementation Requirements

1. **Extract and Validate Token**:
```python
import hmac
import os
from fastapi import Header, HTTPException

def verify_service_token(authorization: str = Header(...)) -> bool:
    """Verify service token from CIRISManager."""
    if not authorization.startswith("Bearer service:"):
        raise HTTPException(status_code=401, detail="Invalid auth scheme")

    provided_token = authorization[len("Bearer service:"):]
    expected_token = os.getenv("CIRIS_SERVICE_TOKEN")

    if not expected_token:
        raise HTTPException(status_code=500, detail="Service token not configured")

    # CRITICAL: Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid service token")

    return True
```

2. **Apply to Shutdown Endpoint**:
```python
@app.post("/v1/system/shutdown")
async def shutdown(
    request: ShutdownRequest,
    auth_valid: bool = Depends(verify_service_token)
):
    # Implementation below
```

## 2. Enhanced Shutdown Endpoint

### Current Behavior (MUST KEEP)
- Endpoint: `POST /v1/system/shutdown`
- Existing functionality for user-initiated shutdowns must remain unchanged

### New Behavior for CD Updates

1. **Detect CD Update Requests**:
   - Check if reason contains "CD update" or "deployment"
   - Check if authorization uses service token

2. **Evaluate Shutdown Safety**:
```python
async def can_shutdown_for_update() -> tuple[bool, str]:
    """Check if agent can safely shutdown for update."""

    # Check 1: Critical tasks
    if await is_processing_critical_task():
        return False, "Processing critical user task"

    # Check 2: Active connections
    active_count = await get_active_connection_count()
    if active_count > 0:
        return False, f"{active_count} active user connections"

    # Check 3: Pending operations
    if await has_pending_operations():
        return False, "Pending operations in queue"

    # Check 4: Recent activity
    last_activity = await get_last_activity_time()
    if time.time() - last_activity < 30:  # Active in last 30 seconds
        return False, "Recent user activity detected"

    return True, "Ready for update"
```

3. **Response Codes**:
   - **HTTP 200**: Agent accepts shutdown, will terminate gracefully
   - **HTTP 503**: Agent is busy, cannot shutdown now
   - **HTTP 401**: Invalid or missing service token
   - **HTTP 400**: Invalid request format

### Complete Implementation Example

```python
from fastapi import FastAPI, HTTPException, Depends, Header, Response
from pydantic import BaseModel
import asyncio
import time
import hmac
import os
import logging

logger = logging.getLogger(__name__)

class ShutdownRequest(BaseModel):
    reason: str
    force: bool = False
    confirm: bool = True

async def verify_service_token(authorization: str = Header(None)) -> bool:
    """Verify service token from CIRISManager."""
    if not authorization:
        return False  # Allow regular auth to handle this

    if not authorization.startswith("Bearer service:"):
        return False  # Not a service token

    provided_token = authorization[len("Bearer service:"):]
    expected_token = os.getenv("CIRIS_SERVICE_TOKEN")

    if not expected_token:
        logger.error("CIRIS_SERVICE_TOKEN not configured")
        return False

    # CRITICAL: Constant-time comparison
    return hmac.compare_digest(provided_token, expected_token)

@app.post("/v1/system/shutdown")
async def shutdown(
    request: ShutdownRequest,
    authorization: str = Header(None),
    response: Response = None
):
    """Handle shutdown requests from users or CIRISManager."""

    # Check if this is a CD update request
    is_cd_update = "CD update" in request.reason or "deployment" in request.reason
    is_service_auth = await verify_service_token(authorization)

    # CD updates MUST use service token
    if is_cd_update and not is_service_auth:
        logger.warning(f"CD update attempted without service token: {request.reason}")
        raise HTTPException(status_code=401, detail="Service token required for CD updates")

    # For CD updates, check if we can safely shutdown
    if is_cd_update:
        can_shutdown, reason = await can_shutdown_for_update()

        if not can_shutdown:
            logger.info(f"Rejecting CD update: {reason}")
            response.status_code = 503
            return {
                "status": "rejected",
                "reason": reason,
                "retry_after": 300  # Suggest retry in 5 minutes
            }

        logger.info(f"Accepting CD update: {request.reason}")
        # Initiate graceful shutdown
        asyncio.create_task(graceful_shutdown(request.reason))
        return {
            "status": "shutdown initiated",
            "reason": request.reason
        }

    # Handle regular user shutdowns (existing logic)
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    # Existing shutdown logic for users...
    logger.info(f"User-initiated shutdown: {request.reason}")
    asyncio.create_task(graceful_shutdown(request.reason))
    return {"status": "shutdown initiated"}

async def graceful_shutdown(reason: str):
    """Perform graceful shutdown."""
    logger.info(f"Starting graceful shutdown: {reason}")

    # 1. Stop accepting new requests
    app.state.shutting_down = True

    # 2. Wait for active requests to complete (max 30 seconds)
    start_time = time.time()
    while await get_active_request_count() > 0:
        if time.time() - start_time > 30:
            logger.warning("Timeout waiting for requests to complete")
            break
        await asyncio.sleep(1)

    # 3. Save state if needed
    await save_agent_state()

    # 4. Exit
    logger.info("Shutdown complete")
    os._exit(0)
```

## 3. Testing Your Implementation

### Test 1: Service Token Validation
```bash
# Should return 401
curl -X POST http://localhost:8080/v1/system/shutdown \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer service:wrong-token" \
  -d '{"reason": "CD update to v1.2.3", "confirm": true}'

# Should return 200 or 503 (depending on agent state)
curl -X POST http://localhost:8080/v1/system/shutdown \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer service:${CIRIS_SERVICE_TOKEN}" \
  -d '{"reason": "CD update to v1.2.3", "confirm": true}'
```

### Test 2: Busy Agent Rejection
```python
# Simulate busy agent
async def is_processing_critical_task():
    return True  # Force busy state

# Should return 503
response = await client.post(
    "/v1/system/shutdown",
    json={"reason": "CD update", "confirm": True},
    headers={"Authorization": f"Bearer service:{token}"}
)
assert response.status_code == 503
```

### Test 3: Regular User Shutdown (unchanged)
```bash
# Should work as before with user auth
curl -X POST http://localhost:8080/v1/system/shutdown \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${USER_TOKEN}" \
  -d '{"reason": "User requested shutdown", "confirm": true}'
```

## 4. Docker Configuration

Ensure your Dockerfile uses the `unless-stopped` restart policy:
```yaml
services:
  agent:
    restart: unless-stopped
```

This allows Docker to automatically restart the container with the new image after shutdown.

## 5. Security Considerations

1. **Never log tokens**: Even partial tokens should not appear in logs
2. **Use constant-time comparison**: Prevents timing attacks
3. **Validate token on every request**: Don't cache validation results
4. **Fail closed**: Reject requests if token validation fails for any reason
5. **Monitor failed attempts**: Log (without tokens) repeated auth failures

## 6. Deployment Flow Summary

1. CIRISManager generates unique service token for agent
2. Token passed as `CIRIS_SERVICE_TOKEN` environment variable
3. Manager encrypts and stores token in its registry
4. During deployment:
   - Manager decrypts token
   - Calls `/v1/system/shutdown` with service auth
   - Agent validates token and checks if safe to shutdown
   - Returns 200 (accept) or 503 (busy)
   - If 200, agent shuts down gracefully
   - Docker restarts container with new image

## 7. Required Response Examples

### Successful Shutdown (HTTP 200)
```json
{
  "status": "shutdown initiated",
  "reason": "CD update to v1.2.3 (deployment abc123)"
}
```

### Busy Agent (HTTP 503)
```json
{
  "status": "rejected",
  "reason": "Processing critical user task",
  "retry_after": 300
}
```

### Invalid Token (HTTP 401)
```json
{
  "detail": "Invalid service token"
}
```

## Implementation Checklist

- [ ] Add `CIRIS_SERVICE_TOKEN` environment variable support
- [ ] Implement constant-time token comparison
- [ ] Add service token validation to shutdown endpoint
- [ ] Implement shutdown safety checks for CD updates
- [ ] Return appropriate HTTP status codes (200, 503, 401)
- [ ] Maintain backward compatibility for user shutdowns
- [ ] Add security logging (without exposing tokens)
- [ ] Test with CIRISManager deployment flow
- [ ] Ensure Docker restart policy is `unless-stopped`
