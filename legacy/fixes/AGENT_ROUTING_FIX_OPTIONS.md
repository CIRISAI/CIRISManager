# Agent Routing Fix Options

## Current Issue
- Manager expects `/agent/{id}` routes to work
- GUI container receives requests but returns 404
- No Next.js routes exist for `/agent/[id]` pattern

## Option 1: Fix in CIRISAgent (Proper Fix)
**Effort**: Medium (requires PR to CIRISAgent repo)
**Time to Deploy**: 1-2 days (PR review + new container deployment)

```typescript
// File: CIRISAgent/CIRISGUI/apps/agui/app/agent/[id]/page.tsx
import { redirect } from 'next/navigation';

export default function AgentPage({ params }: { params: { id: string } }) {
  // Redirect to comms with agent selected
  redirect(`/comms?agent=${params.id}`);
}
```

**Pros**:
- Fixes root cause
- Matches documented architecture
- Clean URLs work as designed

**Cons**:
- Requires modifying CIRISAgent repo
- Needs new GUI container deployment
- Blocks on PR approval

## Option 2: Work Around in Manager (Quick Fix)
**Effort**: Low (Manager-only change)
**Time to Deploy**: 5 minutes

```javascript
// File: CIRISManager/static/manager/manager.js line 295
// Change from:
const url = `/agent/${agentId}`;

// To:
const url = `/comms?agent=${agentId}`;
```

**Pros**:
- Immediate fix
- No cross-repo coordination
- Works with existing GUI

**Cons**:
- Doesn't match architecture docs
- Less clean URLs
- Technical debt

## Recommendation
**For Beta**: Use Option 2 (Manager workaround) - gets users working NOW
**Post-Beta**: Implement Option 1 properly in CIRISAgent

The Manager workaround is ONE LINE and works immediately.
