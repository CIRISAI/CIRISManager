# CIRISManager API Endpoints

Base URL: `https://agents.ciris.ai/manager/v1`

## Authentication
All endpoints require Bearer token authentication:
```bash
Authorization: Bearer <token>
```

Token location: `~/.manager_token` (single line with token)

## Key Endpoints

### Agent Management

#### List Agents
```http
GET /manager/v1/agents
```
Returns list of all agents with status, ports, versions, etc.

#### Get Agent Details
```http
GET /manager/v1/agents/{agent_id}
```
Returns detailed information about a specific agent.

#### Get Agent Configuration (including environment variables)
```http
GET /manager/v1/agents/{agent_id}/config
```
Returns agent's docker-compose environment variables:
```json
{
  "agent_id": "scout-u7e9s3",
  "environment": {
    "OPENAI_API_KEY": "...",
    "DISCORD_BOT_TOKEN": "...",
    ...
  },
  "compose_file": "/opt/ciris/agents/scout-u7e9s3/docker-compose.yml"
}
```

#### Create Agent
```http
POST /manager/v1/agents
Content-Type: application/json

{
  "name": "my-agent",
  "template": "scout",
  "environment": {
    "OPENAI_API_KEY": "...",
    ...
  },
  "use_mock_llm": false,
  "enable_discord": false,
  "server_id": "scout",  // Optional: "main" or "scout"
  "billing_enabled": true,
  "billing_api_key": "..."
}
```

#### Update Agent Configuration
```http
PATCH /manager/v1/agents/{agent_id}/config
Content-Type: application/json

{
  "environment": {
    "NEW_VAR": "value"
  }
}
```

#### Delete Agent
```http
DELETE /manager/v1/agents/{agent_id}
```

#### Start/Stop/Restart Agent
```http
POST /manager/v1/agents/{agent_id}/start
POST /manager/v1/agents/{agent_id}/stop
POST /manager/v1/agents/{agent_id}/restart
```

### Templates

#### List Templates
```http
GET /manager/v1/templates
```

#### Get Template Details
```http
GET /manager/v1/templates/{template_name}/details
```

### Server Management

#### List Servers
```http
GET /manager/v1/servers
```
Returns all configured servers (main, scout, etc.)

#### Get Server Details
```http
GET /manager/v1/servers/{server_id}
```

#### Get Server Stats
```http
GET /manager/v1/servers/{server_id}/stats
```

#### List Agents on Server
```http
GET /manager/v1/servers/{server_id}/agents
```

### Deployment/Updates

#### Get Deployment Status
```http
GET /manager/v1/updates/status
```

#### Notify Update
```http
POST /manager/v1/updates/notify
Content-Type: application/json

{
  "agent_image": "ghcr.io/cirisai/ciris-agent:latest",
  "gui_image": "ghcr.io/cirisai/ciris-gui:latest",
  "strategy": "canary",
  "message": "Update message"
}
```

### System

#### Health Check
```http
GET /manager/v1/health
```

#### Manager Status
```http
GET /manager/v1/status
```

#### Port Allocations
```http
GET /manager/v1/ports/allocated
```

## v2 API

The v2 API is available at `/manager/v2/*` with similar endpoints but different response formats.

### v2 Agent Config
```http
GET /manager/v2/agents/{agent_id}/config
```

## Examples

### Get Agent's Environment Variables
```bash
TOKEN=$(cat ~/.manager_token)
curl -H "Authorization: Bearer $TOKEN" \
  https://agents.ciris.ai/manager/v1/agents/scout-u7e9s3/config \
  | jq '.environment'
```

### Create New Scout on Remote Server
```bash
TOKEN=$(cat ~/.manager_token)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  https://agents.ciris.ai/manager/v1/agents \
  -d '{
    "name": "scout-remote-test",
    "template": "scout",
    "server_id": "scout",
    "environment": {
      "OPENAI_API_KEY": "...",
      "CIRIS_ADAPTER": "api"
    },
    "use_mock_llm": false,
    "enable_discord": false,
    "billing_enabled": true
  }'
```

### List All Agents with JQ
```bash
TOKEN=$(cat ~/.manager_token)
curl -H "Authorization: Bearer $TOKEN" \
  https://agents.ciris.ai/manager/v1/agents \
  | jq '.agents[] | {agent_id, agent_name, server_id, status, api_port}'
```
