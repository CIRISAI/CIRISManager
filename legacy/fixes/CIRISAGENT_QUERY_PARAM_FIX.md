# Vision Seed: Fix Agent Switching in CIRIS GUI

## 🎯 THE PROBLEM
Users cannot switch between agents using URLs. Once an agent is selected, it's stored in localStorage and the GUI ignores URL changes. This breaks the Manager's "Open" button functionality.

**Current broken flow:**
1. User clicks "Open" on Agent A → Works, saves to localStorage
2. User clicks "Open" on Agent B → Still shows Agent A (localStorage wins)
3. Only solution: Logout and login again

## 🌱 THE FIX
Add query parameter support to AgentContextHybrid so URLs like `/comms?agent=datum` work as expected.

**File to modify:**
`CIRISGUI/apps/agui/contexts/AgentContextHybrid.tsx`

**Priority order should be:**
1. Query parameter (`?agent=datum`) - explicit user intent
2. Path parameter (`/agent/datum`) - managed mode
3. localStorage - helpful persistence
4. Default - fallback

## 🔧 IMPLEMENTATION HINTS

Around line 196 where localStorage is checked, add query param detection FIRST:

```typescript
// Check URL query params first (highest priority)
const urlParams = new URLSearchParams(window.location.search);
const queryAgent = urlParams.get('agent');
if (queryAgent) {
  selectAgent(queryAgent);
  return; // Query param wins
}

// Then existing localStorage check
const savedAgentId = localStorage.getItem('selectedAgentId');
if (savedAgentId) {
  selectAgent(savedAgentId);
}
```

## 📊 TEST SCENARIOS
1. `/comms?agent=agentA` → Shows Agent A
2. `/comms?agent=agentB` → Switches to Agent B (even with localStorage)
3. `/comms` (no query) → Uses localStorage or default
4. Bookmark with `?agent=datum` → Always opens correct agent

## 🎪 WHY THIS MATTERS
- Manager "Open" buttons will work correctly
- URLs become shareable/bookmarkable
- Users can switch agents without logout
- Preserves helpful persistence when no query param

## 🚀 BRANCH SUGGESTION
`fix/agent-query-param-switching`

This is a ~20 line fix that will dramatically improve the multi-agent UX. The Manager side is already fixed to use `/comms?agent={id}` - we just need the GUI to honor it.
