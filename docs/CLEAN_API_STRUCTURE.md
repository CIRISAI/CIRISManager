# Clean API Structure - No Legacy

## Core Principles
- Each namespace owns ONE concern
- No redundancy
- Clear RESTful patterns
- Flat is better than nested (unless ownership is clear)

## Complete API Structure

### 1. Agents Namespace - `/agents`
**Purpose**: Agent lifecycle and configuration ONLY

```yaml
GET    /agents                      # List all agents
POST   /agents                      # Create new agent
GET    /agents/{agent_id}           # Get specific agent
DELETE /agents/{agent_id}           # Delete agent

# Lifecycle
POST   /agents/{agent_id}/start     # Start agent
POST   /agents/{agent_id}/stop      # Stop agent
POST   /agents/{agent_id}/restart   # Restart agent

# Configuration
GET    /agents/{agent_id}/config    # Get config
PATCH  /agents/{agent_id}/config    # Update config

# OAuth
POST   /agents/{agent_id}/oauth     # Setup OAuth
DELETE /agents/{agent_id}/oauth     # Remove OAuth

# Filters
GET    /agents?deployment=PILOT_A   # Filter by deployment
GET    /agents?template=sage        # Filter by template
GET    /agents?status=running       # Filter by status
```

### 2. Versions Namespace - `/versions`
**Purpose**: ALL version tracking and history

```yaml
# Current State
GET    /versions                    # Current versions of all components
GET    /versions/{component}        # Current version of component (agent/gui/nginx)

# Fleet Versions
GET    /versions/fleet              # All agent versions with adoption metrics
GET    /versions/fleet/{agent_id}   # Specific agent version info

# History
GET    /versions/history            # Complete version history
GET    /versions/history/{component} # Component-specific history

# Rollback
GET    /versions/rollback           # Available rollback versions
POST   /versions/rollback           # Execute rollback
```

### 3. Deployments Namespace - `/deployments`
**Purpose**: Deployment orchestration and CD

```yaml
# CD Integration
POST   /deployments/webhook         # GitHub Actions webhook

# Deployment Management
GET    /deployments                 # List all deployments
POST   /deployments                 # Create deployment
GET    /deployments/{id}           # Get deployment status
DELETE /deployments/{id}           # Cancel deployment

# Deployment Control
POST   /deployments/{id}/execute   # Execute deployment
POST   /deployments/{id}/pause     # Pause deployment
POST   /deployments/{id}/rollback  # Rollback deployment

# Single Agent Deployments
POST   /deployments/target          # Deploy to specific agent(s)
```

### 4. Templates Namespace - `/templates`
**Purpose**: Agent template management

```yaml
GET    /templates                   # List available templates
GET    /templates/{name}            # Get template details
POST   /templates/{name}/validate   # Validate template
```

### 5. System Namespace - `/system`
**Purpose**: Manager system operations

```yaml
GET    /system/health              # Health check
GET    /system/status              # Manager status
GET    /system/metrics             # System metrics
GET    /system/ports               # Port allocations
```

## What Gets Deleted

### Remove These Endpoints Completely:
```
DELETE /agents/versions             → Use /versions/fleet
DELETE /versions/adoption           → Merged into /versions/fleet
DELETE /updates/*                   → Entire namespace replaced by /deployments
DELETE /updates/current-images      → Use /versions
DELETE /updates/rollback-options    → Use /versions/rollback
DELETE /updates/history             → Use /versions/history
DELETE /updates/pending             → Not needed
DELETE /updates/pending/all         → Not needed
DELETE /canary/*                    → Overcomplicated, use deployments
DELETE /dashboard/*                 → Separate concern
```

## Clean Data Models

### Agent Model
```python
class Agent:
    agent_id: str
    name: str
    container_name: str
    template: str
    deployment: str  # e.g., "CIRIS_DISCORD_PILOT"
    status: str      # running/stopped
    port: int
    # NO version info here - get from /versions/fleet/{agent_id}
```

### Version Model
```python
class Version:
    component: str   # agent/gui/nginx
    current: str     # image:tag
    previous: str    # n-1 image:tag
    rollback: str    # n-2 image:tag
    deployed_at: datetime
    deployed_by: str
```

### Deployment Model
```python
class Deployment:
    id: str
    status: str      # pending/executing/complete/failed
    strategy: str    # immediate/canary/staged
    targets: List[str]  # Component types or agent IDs
    versions: Dict[str, str]  # component -> version
    created_at: datetime
    executed_at: Optional[datetime]
```

## Clean Implementation

### File Structure
```
ciris_manager/api/
├── __init__.py
├── agents.py       # /agents endpoints
├── versions.py     # /versions endpoints
├── deployments.py  # /deployments endpoints
├── templates.py    # /templates endpoints
├── system.py       # /system endpoints
└── models.py       # Pydantic models
```

### Example: Clean Agents Endpoint
```python
# agents.py
@router.get("/agents")
async def list_agents(
    deployment: Optional[str] = None,
    template: Optional[str] = None,
    status: Optional[str] = None
) -> List[Agent]:
    """List agents with optional filters."""
    agents = discover_agents()

    if deployment:
        agents = [a for a in agents if a.deployment == deployment]
    if template:
        agents = [a for a in agents if a.template == template]
    if status:
        agents = [a for a in agents if a.status == status]

    return agents
```

### Example: Clean Versions Endpoint
```python
# versions.py
@router.get("/versions/fleet")
async def get_fleet_versions() -> FleetVersions:
    """Get version info for all agents."""
    agents = discover_agents()

    versions = {}
    adoption = {}

    for agent in agents:
        version = get_agent_version(agent.agent_id)
        versions[agent.agent_id] = version

        if version not in adoption:
            adoption[version] = []
        adoption[version].append(agent.agent_id)

    return FleetVersions(
        versions=versions,
        adoption=adoption,
        total_agents=len(agents)
    )
```

## Benefits of Clean Structure

1. **50% fewer endpoints** (35 instead of 70+)
2. **Clear ownership** - each namespace has ONE job
3. **No redundancy** - single source of truth
4. **Predictable** - consistent patterns everywhere
5. **Fast** - no legacy checks or transformations

## Migration Steps

1. **Stop all agents** (we only have 2 beta agents)
2. **Delete old API files**
3. **Create new clean API files**
4. **Update UI to use new endpoints**
5. **Restart agents**
6. **Done** - no compatibility layer needed

## UI Changes Required

```javascript
// OLD
fetch('/manager/v1/agents/versions')
fetch('/manager/v1/updates/rollback-options')

// NEW
fetch('/manager/v1/versions/fleet')
fetch('/manager/v1/versions/rollback')
```

## Database Changes

None required - we're just reorganizing endpoints, not data.

## Total Implementation Time

**2 days** - because we're not maintaining compatibility:
- Day 1: Implement new endpoints, delete old ones
- Day 2: Update UI, test, deploy
