# Manager UI API Migration Plan

## Current API Calls Analysis

All API calls in `manager.js` currently use the native `fetch()` API with `credentials: 'include'` for cookie-based authentication.

### Agent Management APIs

1. **List Agents**
   - Line 36: `GET /manager/v1/agents`
   - Line 2527: `GET /manager/v1/agents` (duplicate for agent picker)
   
2. **Get Agent Versions**
   - Line 173: `GET /manager/v1/agents/versions`

3. **Agent Lifecycle Control**
   - Line 595: `POST /manager/v1/agents/${agentId}/restart`
   - Line 620: `POST /manager/v1/agents/${agentId}/start`
   - Line 651: `POST /manager/v1/agents/${agentId}/shutdown`
   - Line 685: `POST /manager/v1/agents/${agentId}/stop`

4. **Delete Agent**
   - Line 715: `DELETE /manager/v1/agents/${agentId}`

5. **Agent Configuration**
   - Line 1618: `GET /manager/v1/agents/${agentId}/config`
   - Line 1814: `PATCH /manager/v1/agents/${agentId}/config`

6. **Create Agent**
   - Line 564: `POST /manager/v1/agents`

### Deployment Management APIs

1. **Deployment Status**
   - Line 2452: `GET /manager/v1/updates/status`
   - Line 2774: `GET /manager/v1/updates/status` (for rollback dialog)

2. **Pending Deployments**
   - Line 2283: `GET /manager/v1/updates/pending`

3. **Deployment Actions**
   - Line 2375: `POST /manager/v1/updates/${action}` (launch/reject/pause)

4. **Current Images**
   - Line 2431: `GET /manager/v1/updates/current-images`

5. **Deployment History**
   - Line 2494: `GET /manager/v1/updates/history?limit=10`

6. **Rollback**
   - Line 2591: `GET /manager/v1/updates/rollback-options`
   - Line 2799: `POST /manager/v1/updates/rollback`

### Telemetry/Dashboard APIs

1. **Dashboard Agents**
   - Line 1851: `GET /manager/v1/dashboard/agents`

2. **Manager Status**
   - Line 37: `GET /manager/v1/status`

### Canary/Version Management APIs

1. **Canary Groups**
   - Line 739: `GET /manager/v1/canary/groups`
   - Line 864: `POST /manager/v1/canary/agent/${agentId}/group`

2. **Version Adoption**
   - Line 885: `GET /manager/v1/versions/adoption`

### Template Management APIs

1. **List Templates**
   - Line 278: `GET /manager/v1/templates`

2. **Template Details**
   - Line 322: `GET /manager/v1/templates/${template}/details`

### Environment Configuration APIs

1. **Default Environment**
   - Line 461: `GET /manager/v1/env/default`

### OAuth/Authentication APIs

1. **OAuth Logout**
   - Line 1308: `POST /manager/v1/oauth/logout`

2. **OAuth Verify** (uses API_BASE variable)
   - Line 1533: `GET ${API_BASE}/agents/${agentId}/oauth/verify`

3. **OAuth Complete** (uses API_BASE variable)
   - Line 1578: `POST ${API_BASE}/agents/${agentId}/oauth/complete`

## Migration Strategy

### Phase 1: Setup SDK
1. Build browser-compatible version of SDK
2. Include SDK in index.html
3. Initialize SDK client with proper configuration

### Phase 2: Migrate by Module
1. **Agent Management** - Replace all agent CRUD operations
2. **Deployments** - Replace deployment monitoring and control
3. **Telemetry** - Replace dashboard and status calls
4. **Templates/Config** - These aren't in SDK yet, keep as raw fetch for now

### Phase 3: Error Handling
1. Update error handling to use SDK error types
2. Implement retry logic using SDK's built-in retries
3. Handle authentication failures with SDK callbacks

### Non-SDK APIs (Keep as fetch)
These endpoints are not covered by the current SDK and should remain as fetch calls:
- Templates (`/manager/v1/templates/*`)
- Environment defaults (`/manager/v1/env/default`)
- Canary groups (`/manager/v1/canary/*`)
- OAuth endpoints (`/manager/v1/oauth/*`)
- Dashboard agents (`/manager/v1/dashboard/agents`)
- Version adoption (`/manager/v1/versions/adoption`)

## Benefits of Migration
1. **Type Safety** - TypeScript types for all API calls
2. **Consistent Error Handling** - Centralized error handling
3. **Automatic Retries** - Built-in retry logic for failed requests
4. **Better Authentication** - Token-based auth support
5. **Reduced Boilerplate** - No need to repeat credentials, headers, etc.