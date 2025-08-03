# CIRISManager API Documentation

## Overview

CIRISManager provides a RESTful API for managing CIRIS agents. All endpoints are prefixed with `/manager/v1`.

## Authentication

Authentication depends on the configured mode:

- **Development Mode** (`auth.mode: development`): No authentication required
- **Production Mode** (`auth.mode: production`): OAuth bearer token required

## API Endpoints

### Health & Status

#### GET /manager/v1/health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "ciris-manager"
}
```

#### GET /manager/v1/status
Get manager status and component information.

**Response:**
```json
{
  "status": "running",
  "version": "1.0.0",
  "components": {
    "watchdog": "running",
    "api_server": "running",
    "nginx": "disabled"
  },
  "auth_mode": "development"
}
```

### Agent Management

#### GET /manager/v1/agents
List all discovered agents (from Docker containers).

**Response:**
```json
{
  "agents": [
    {
      "agent_id": "scout-abc123",
      "name": "Scout",
      "type": "scout",
      "status": "running",
      "port": 8001,
      "container": "ciris-scout-abc123",
      "api_endpoint": "http://localhost:8001"
    }
  ]
}
```

#### GET /manager/v1/agents/{agent_name}
Get specific agent details by name.

**Parameters:**
- `agent_name`: Agent name (e.g., "scout")

**Response:**
```json
{
  "agent_id": "scout-abc123",
  "name": "Scout",
  "port": 8001,
  "template": "scout",
  "api_endpoint": "http://localhost:8001",
  "compose_file": "/opt/ciris/agents/scout-abc123/docker-compose.yml",
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### POST /manager/v1/agents
Create a new agent from template.

**Request Body:**
```json
{
  "template": "scout",
  "name": "Scout Agent",
  "environment": {
    "CUSTOM_VAR": "value"
  },
  "wa_signature": "optional-signature-for-custom-templates"
}
```

**Response:**
```json
{
  "agent_id": "scout-abc123",
  "name": "Scout Agent",
  "container": "ciris-scout-abc123",
  "port": 8001,
  "api_endpoint": "http://localhost:8001",
  "template": "scout",
  "status": "starting"
}
```

#### DELETE /manager/v1/agents/{agent_id}
Delete an agent and clean up resources.

**Parameters:**
- `agent_id`: Agent ID (e.g., "scout-abc123")

**Response:**
```json
{
  "status": "deleted",
  "agent_id": "scout-abc123",
  "message": "Agent scout-abc123 and all its resources have been removed"
}
```

### Templates

#### GET /manager/v1/templates
List available agent templates.

**Response:**
```json
{
  "templates": {
    "scout": "Scout agent template",
    "sage": "Sage agent template",
    "echo": "Echo agent template"
  },
  "pre_approved": ["scout", "sage", "echo"]
}
```

### Port Management

#### GET /manager/v1/ports/allocated
Show port allocations.

**Response:**
```json
{
  "allocated": {
    "scout-abc123": 8001,
    "sage-xyz789": 8002
  },
  "reserved": [8080, 8888],
  "range": {
    "start": 8000,
    "end": 8999
  }
}
```

### OAuth Endpoints (Production Mode)

#### GET /manager/v1/oauth/login
Initiate OAuth login flow.

**Parameters:**
- `redirect_uri` (optional): Where to redirect after auth

#### GET /manager/v1/oauth/callback
OAuth callback endpoint (handled automatically).

#### POST /manager/v1/oauth/logout
Logout and clear session.

**Response:**
```json
{
  "message": "Logged out successfully"
}
```

#### GET /manager/v1/oauth/user
Get current authenticated user.

**Headers:**
- `Authorization: Bearer <token>`

**Response:**
```json
{
  "user": {
    "id": "user-123",
    "email": "user@ciris.ai",
    "name": "User Name"
  }
}
```

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error description"
}
```

Common HTTP status codes:
- 400: Bad Request
- 401: Unauthorized (missing/invalid auth)
- 403: Forbidden (insufficient permissions)
- 404: Not Found
- 500: Internal Server Error

## Development Tips

### Using the API in Development Mode

```bash
# Set development mode
export CIRIS_AUTH_MODE=development

# Create an agent
curl -X POST http://localhost:8888/manager/v1/agents \
  -H "Content-Type: application/json" \
  -d '{"template": "scout", "name": "Test Scout"}'

# List agents
curl http://localhost:8888/manager/v1/agents

# Delete an agent
curl -X DELETE http://localhost:8888/manager/v1/agents/scout-abc123
```

### Using the API in Production Mode

```bash
# Get auth token first
TOKEN=$(curl -X POST http://localhost:8888/manager/v1/oauth/login | jq -r .access_token)

# Use token in requests
curl http://localhost:8888/manager/v1/agents \
  -H "Authorization: Bearer $TOKEN"
```
