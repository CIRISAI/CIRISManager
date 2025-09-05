# Clean API Rollout Plan - Test in Prod via CI/CD

## Strategy: Incremental Rollout with Production Validation

We'll implement each namespace cleanly, push to GitHub, let CI/CD deploy, and validate in production before moving to the next namespace.

## Phase 1: Create Clean Structure (Local)
**Time: 30 minutes**

### Step 1.1: Create new API module structure
```bash
mkdir -p ciris_manager/api/v2
touch ciris_manager/api/v2/__init__.py
touch ciris_manager/api/v2/agents.py
touch ciris_manager/api/v2/versions.py
touch ciris_manager/api/v2/deployments.py
touch ciris_manager/api/v2/templates.py
touch ciris_manager/api/v2/system.py
touch ciris_manager/api/v2/models.py
```

### Step 1.2: Create shared models
```python
# ciris_manager/api/v2/models.py
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime

class Agent(BaseModel):
    agent_id: str
    name: str
    container_name: str
    template: str
    deployment: str
    status: str
    port: int

class Version(BaseModel):
    component: str
    current: str
    previous: Optional[str]
    rollback: Optional[str]
    deployed_at: datetime
    deployed_by: str

class Deployment(BaseModel):
    id: str
    status: str
    strategy: str
    targets: List[str]
    versions: Dict[str, str]
    created_at: datetime
```

### Step 1.3: Mount v2 API alongside v1
```python
# In main app.py
from ciris_manager.api.v2 import agents, versions, deployments, templates, system

# Keep v1 running
app.include_router(v1_router, prefix="/manager/v1")

# Add v2 alongside
app.include_router(agents.router, prefix="/manager/v2")
app.include_router(versions.router, prefix="/manager/v2")
app.include_router(deployments.router, prefix="/manager/v2")
app.include_router(templates.router, prefix="/manager/v2")
app.include_router(system.router, prefix="/manager/v2")
```

## Phase 2: Implement & Deploy System Namespace
**Time: 1 hour**

### Step 2.1: Implement /system endpoints
```python
# ciris_manager/api/v2/system.py
@router.get("/system/health")
@router.get("/system/status")
@router.get("/system/ports")
```

### Step 2.2: Push and deploy
```bash
git add ciris_manager/api/v2/
git commit -m "feat: Add v2 API with /system namespace"
git push
```

### Step 2.3: Production validation
```bash
# After CI/CD deploys (watch GitHub Actions)
curl https://agents.ciris.ai/manager/v2/system/health
curl https://agents.ciris.ai/manager/v2/system/status

# Verify v1 still works
curl https://agents.ciris.ai/manager/v1/health
```

✅ **Checkpoint**: Both v1 and v2 responding

## Phase 3: Implement & Deploy Agents Namespace
**Time: 2 hours**

### Step 3.1: Implement /agents endpoints
```python
# ciris_manager/api/v2/agents.py
@router.get("/agents")
@router.post("/agents")
@router.get("/agents/{agent_id}")
@router.delete("/agents/{agent_id}")
@router.post("/agents/{agent_id}/start")
@router.post("/agents/{agent_id}/stop")
@router.post("/agents/{agent_id}/restart")
@router.get("/agents/{agent_id}/config")
@router.patch("/agents/{agent_id}/config")
@router.post("/agents/{agent_id}/oauth")
```

### Step 3.2: Test locally with our agents
```bash
# Local test
curl localhost:8888/manager/v2/agents
```

### Step 3.3: Push and deploy
```bash
git commit -m "feat: Add v2 /agents namespace"
git push
```

### Step 3.4: Production validation
```bash
# List agents
curl https://agents.ciris.ai/manager/v2/agents

# Get Datum
curl https://agents.ciris.ai/manager/v2/agents/datum

# Get Sage
curl https://agents.ciris.ai/manager/v2/agents/sage-2wnuc8

# Test filters
curl "https://agents.ciris.ai/manager/v2/agents?deployment=CIRIS_DISCORD_PILOT"
```

✅ **Checkpoint**: Can see and control both beta agents via v2

## Phase 4: Implement & Deploy Versions Namespace
**Time: 2 hours**

### Step 4.1: Implement /versions endpoints
```python
# ciris_manager/api/v2/versions.py
@router.get("/versions")
@router.get("/versions/{component}")
@router.get("/versions/fleet")
@router.get("/versions/fleet/{agent_id}")
@router.get("/versions/history")
@router.get("/versions/rollback")
@router.post("/versions/rollback")
```

### Step 4.2: Push and deploy
```bash
git commit -m "feat: Add v2 /versions namespace"
git push
```

### Step 4.3: Production validation
```bash
# Get current versions
curl https://agents.ciris.ai/manager/v2/versions

# Get fleet versions
curl https://agents.ciris.ai/manager/v2/versions/fleet

# Check rollback options
curl https://agents.ciris.ai/manager/v2/versions/rollback
```

✅ **Checkpoint**: Version tracking working for both agents

## Phase 5: Implement & Deploy Deployments Namespace
**Time: 2 hours**

### Step 5.1: Implement /deployments endpoints
```python
# ciris_manager/api/v2/deployments.py
@router.post("/deployments/webhook")
@router.get("/deployments")
@router.post("/deployments")
@router.get("/deployments/{id}")
@router.post("/deployments/{id}/execute")
@router.post("/deployments/target")
```

### Step 5.2: Push and deploy
```bash
git commit -m "feat: Add v2 /deployments namespace"
git push
```

### Step 5.3: Production validation
```bash
# List deployments
curl https://agents.ciris.ai/manager/v2/deployments

# Test single agent deployment (dry run)
curl -X POST https://agents.ciris.ai/manager/v2/deployments/target \
  -d '{"agent_id": "datum", "version": "current", "dry_run": true}'
```

✅ **Checkpoint**: Deployment system accessible

## Phase 6: Implement & Deploy Templates Namespace
**Time: 1 hour**

### Step 6.1: Implement /templates endpoints
```python
# ciris_manager/api/v2/templates.py
@router.get("/templates")
@router.get("/templates/{name}")
@router.post("/templates/{name}/validate")
```

### Step 6.2: Push and deploy
```bash
git commit -m "feat: Add v2 /templates namespace"
git push
```

### Step 6.3: Production validation
```bash
# List templates
curl https://agents.ciris.ai/manager/v2/templates

# Get template details
curl https://agents.ciris.ai/manager/v2/templates/default
```

✅ **Checkpoint**: All v2 namespaces operational

## Phase 7: Update UI to Use v2
**Time: 2 hours**

### Step 7.1: Update manager.js endpoints
```javascript
// OLD
const API_BASE = '/manager/v1';

// NEW
const API_BASE = '/manager/v2';

// Update all fetch calls:
// /agents/versions → /versions/fleet
// /updates/* → /deployments/*
```

### Step 7.2: Test UI locally
```bash
# Open browser to localhost:8888
# Verify all functionality works
```

### Step 7.3: Push and deploy
```bash
git commit -m "feat: Update UI to use v2 API"
git push
```

### Step 7.4: Production validation
```bash
# Open https://agents.ciris.ai
# Check all UI functions:
# - Agent list ✓
# - Start/stop agents ✓
# - View versions ✓
# - Deployment controls ✓
```

✅ **Checkpoint**: UI fully functional with v2

## Phase 8: Remove v1 API
**Time: 30 minutes**

### Step 8.1: Remove v1 router from app
```python
# app.py
# app.include_router(v1_router, prefix="/manager/v1")  # DELETE THIS
app.include_router(agents.router, prefix="/manager/v2")
# ... rest of v2 routers
```

### Step 8.2: Delete old files
```bash
rm ciris_manager/api/routes.py  # 2400 lines gone!
rm -rf ciris_manager/api/legacy/
```

### Step 8.3: Push and deploy
```bash
git commit -m "feat: Remove v1 API - v2 is live!"
git push
```

### Step 8.4: Final production validation
```bash
# v1 should 404
curl https://agents.ciris.ai/manager/v1/agents  # Should fail

# v2 should work
curl https://agents.ciris.ai/manager/v2/agents  # Should work
```

✅ **Checkpoint**: Clean API deployed!

## Rollback Plan

At ANY point if something breaks:

```bash
# Quick revert
git revert HEAD
git push

# CI/CD will deploy previous version in ~3 minutes
```

## Success Metrics

- [ ] Both beta agents (Datum, Sage) accessible via v2
- [ ] UI fully functional
- [ ] No v1 endpoints remaining
- [ ] Code reduced by >1000 lines
- [ ] All endpoints return in <200ms

## Timeline

**Total: 1 day of implementation**

- Morning: Phases 1-4 (System, Agents, Versions)
- Afternoon: Phases 5-7 (Deployments, Templates, UI)
- Evening: Phase 8 (Cleanup)

**Each push triggers CI/CD (~3 minutes to prod)**

## Monitoring During Rollout

Watch these in real-time:

```bash
# SSH to prod
ssh -i ~/.ssh/ciris_deploy root@108.61.119.117

# Watch manager logs
journalctl -u ciris-manager -f

# Watch agent status
docker ps | grep ciris

# Check endpoints
curl localhost:8888/manager/v2/system/health
```

## Go/No-Go Checklist

Before each phase:
- ✅ Previous phase validated in prod
- ✅ Both agents still running
- ✅ No errors in logs
- ✅ UI still functional

## Let's Roll!

Start with Phase 1 now and incrementally deploy through CI/CD. Each phase gets validated in production before moving forward. If anything breaks, we revert and fix.
