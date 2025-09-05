# API Namespace Consolidation Plan

## Executive Summary
Consolidate and reorganize the `/agents/` and `/versions/` namespaces to create a more logical, RESTful API structure that clearly separates concerns and reduces redundancy.

## Current State Analysis

### Agents Namespace (`/agents/*`)
Currently handles:
- CRUD operations (create, read, delete)
- Lifecycle management (start, stop, restart, shutdown)
- Configuration management
- OAuth setup
- Version information (misplaced)
- Deployment assignment

### Versions Namespace (`/versions/*`)
Currently handles:
- Version adoption metrics (only one endpoint!)

### Updates Namespace (`/updates/*`)
Currently handles:
- Deployment notifications and orchestration
- Rollback operations
- Version history
- Image tracking
- Changelog access

## Problems Identified

1. **Version information scattered across namespaces**
   - `/agents/versions` - Agent version info
   - `/versions/adoption` - Version adoption metrics
   - `/updates/rollback-options` - Version rollback options
   - `/updates/current-images` - Current version tracking
   - `/updates/history` - Version history

2. **Unclear separation of concerns**
   - Agent lifecycle mixed with version info
   - Deployment operations split between updates and agents

3. **Redundant endpoints**
   - `/updates/pending` vs `/updates/pending/all`
   - Version info available in multiple places

## Proposed Consolidated Structure

### Phase 1: Reorganize Agents Namespace

```yaml
/agents:
  # Core Agent Operations
  GET    /                           # List all agents
  POST   /                           # Create new agent
  GET    /{agent_id}                 # Get specific agent
  DELETE /{agent_id}                 # Delete agent

  # Lifecycle Management
  POST   /{agent_id}/start           # Start agent
  POST   /{agent_id}/stop            # Stop agent
  POST   /{agent_id}/restart         # Restart agent
  POST   /{agent_id}/shutdown        # Graceful shutdown

  # Configuration
  GET    /{agent_id}/config          # Get agent config
  PATCH  /{agent_id}/config          # Update agent config

  # OAuth
  GET    /{agent_id}/oauth/status    # OAuth status
  POST   /{agent_id}/oauth/setup     # Setup OAuth
  POST   /{agent_id}/oauth/verify    # Verify OAuth

  # Deployment Association
  PUT    /{agent_id}/deployment      # Set deployment

  # Grouped Queries
  GET    /by-deployment/{deployment} # Get agents by deployment
  GET    /by-template/{template}     # Get agents by template
  GET    /by-status/{status}         # Get agents by status
```

### Phase 2: Create Unified Versions Namespace

```yaml
/versions:
  # Current State
  GET    /current                    # Current versions of all components
  GET    /current/{component_type}   # Current version of specific component

  # Version Information
  GET    /agents                     # All agent versions (moved from /agents/versions)
  GET    /agent/{agent_id}           # Specific agent version info
  GET    /gui                        # GUI version info
  GET    /nginx                      # Nginx version info

  # Adoption & Metrics
  GET    /adoption                   # Version adoption across fleet
  GET    /adoption/{version}         # Adoption for specific version
  GET    /metrics                    # Version deployment metrics

  # History & Rollback
  GET    /history                    # Complete version history
  GET    /history/{component_type}   # History for specific component
  GET    /rollback-options           # Available rollback versions
  GET    /rollback-options/{component_type}  # Rollback for specific component

  # Staging
  GET    /staged                     # All staged versions
  POST   /stage                      # Stage a new version
  POST   /promote/{component_type}   # Promote staged to current

  # Comparisons
  GET    /diff/{version1}/{version2} # Compare two versions
  GET    /changelog/{version}        # Changelog for version
```

### Phase 3: Streamline Deployments Namespace

```yaml
/deployments:  # Rename from /updates for clarity
  # Deployment Orchestration
  POST   /notify                     # CD notification (webhook)
  POST   /create                     # Create new deployment
  GET    /                           # List all deployments
  GET    /{deployment_id}            # Get deployment details
  GET    /{deployment_id}/status     # Deployment status
  GET    /{deployment_id}/events     # SSE events stream

  # Deployment Control
  POST   /{deployment_id}/launch     # Launch deployment
  POST   /{deployment_id}/pause      # Pause deployment
  POST   /{deployment_id}/cancel     # Cancel deployment
  POST   /{deployment_id}/rollback   # Initiate rollback

  # Single Agent Deployments
  POST   /agent/{agent_id}/deploy    # Deploy to single agent

  # Pending Operations
  GET    /pending                    # Pending deployments summary
  GET    /pending/details            # Detailed pending info

  # Rollback Management
  GET    /rollback-proposals         # Active rollback proposals
  POST   /rollback-proposals/{id}/approve  # Approve rollback
  POST   /rollback-proposals/{id}/reject   # Reject rollback
```

## Implementation Plan

### Step 1: Add New Endpoints (Non-Breaking)
**Timeline: Week 1**
- Implement new `/versions/*` endpoints
- Implement new `/deployments/*` endpoints
- Keep old endpoints functional with deprecation warnings

### Step 2: Update SDK and Documentation
**Timeline: Week 2**
- Update TypeScript SDK to use new endpoints
- Update OpenAPI specification
- Create migration guide

### Step 3: Migrate UI
**Timeline: Week 3**
- Update manager UI to use new endpoints
- Add fallback logic for backward compatibility
- Test thoroughly with both old and new endpoints

### Step 4: Deprecation Notices
**Timeline: Week 4**
- Add deprecation headers to old endpoints
- Log deprecation warnings
- Notify users via changelog

### Step 5: Remove Old Endpoints
**Timeline: After 3 months**
- Remove deprecated endpoints
- Clean up code
- Update all documentation

## Benefits

1. **Clear Separation of Concerns**
   - Agents: Instance management
   - Versions: Version tracking and history
   - Deployments: Deployment orchestration

2. **Improved Discoverability**
   - Logical grouping makes API easier to explore
   - Consistent patterns across namespaces

3. **Reduced Redundancy**
   - Single source of truth for each data type
   - Eliminated duplicate endpoints

4. **Better RESTful Design**
   - Resources clearly identified
   - Operations follow REST conventions

5. **Easier Maintenance**
   - Related code grouped together
   - Clear module boundaries

## Migration Examples

### Example 1: Getting Agent Versions
```bash
# Old
GET /agents/versions

# New
GET /versions/agents
```

### Example 2: Getting Rollback Options
```bash
# Old
GET /updates/rollback-options

# New
GET /versions/rollback-options
```

### Example 3: Deploying to Single Agent
```bash
# Old
POST /updates/deploy-single
{
  "agent_id": "datum",
  "version": "1.0.5"
}

# New
POST /deployments/agent/datum/deploy
{
  "version": "1.0.5"
}
```

## Backward Compatibility Strategy

### Phase 1: Dual Support (3 months)
```python
# Old endpoint with deprecation warning
@router.get("/agents/versions", deprecated=True)
async def get_agent_versions_legacy():
    warnings.warn("Use /versions/agents instead", DeprecationWarning)
    return await get_agent_versions()

# New endpoint
@router.get("/versions/agents")
async def get_agent_versions():
    # Implementation
```

### Phase 2: Breaking Change Notice
- Add `X-Deprecation-Date` header
- Return deprecation notice in response
- Log usage for monitoring

### Phase 3: Removal
- Return 410 Gone with migration instructions
- Eventually remove code

## Risk Mitigation

1. **Extensive Testing**
   - Unit tests for all new endpoints
   - Integration tests for migration paths
   - Load testing to ensure performance

2. **Gradual Rollout**
   - Feature flag for new endpoints
   - Canary deployment to test with subset

3. **Monitoring**
   - Track usage of old vs new endpoints
   - Alert on high error rates
   - Monitor migration progress

4. **Rollback Plan**
   - Keep old code in separate module
   - Quick revert capability
   - Database migrations reversible

## Success Metrics

- **API Usage**: >80% traffic on new endpoints within 2 months
- **Error Rate**: <0.1% increase in API errors
- **Developer Satisfaction**: Positive feedback on clarity
- **Code Reduction**: 20% less code through consolidation
- **Documentation**: 100% coverage of new endpoints

## Next Steps

1. **Review and Approval**: Get stakeholder buy-in
2. **Detailed Design**: Create OpenAPI spec for new structure
3. **Prototype**: Implement `/versions` namespace first
4. **Testing**: Comprehensive test suite
5. **Rollout**: Gradual deployment with monitoring
