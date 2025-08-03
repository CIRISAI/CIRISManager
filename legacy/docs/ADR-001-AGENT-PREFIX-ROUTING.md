# ADR-001: Keep /agent/ Prefix Despite UX Tradeoff

## Status
Accepted (December 2024)

## Context
Users expect clean URLs like `agents.ciris.ai/datum` but we require `agents.ciris.ai/agent/datum`. Both CIRISAgent and CIRISManager teams independently identified this UX issue.

## Decision
We will KEEP the `/agent/{id}` prefix pattern despite the UX tradeoff.

## Rationale

### 1. Mode Detection Signal
The GUI uses URL path to auto-detect deployment mode:
- `/agent/*` = Managed mode (multi-agent)
- `/` = Standalone mode (single agent)

This is **load-bearing architecture** - the GUI's behavior changes based on this detection.

### 2. Namespace Separation
```
/api/{agent-id}/*    → Agent APIs
/agent/{agent-id}/*  → Agent GUIs
/manager/*           → Manager interface
/health              → System health
```

Without prefixes, agent names would collide with system routes.

### 3. Backward Compatibility
Thousands of standalone deployments rely on the GUI working at `/`. Changing mode detection would break them.

### 4. Future Flexibility
Agents may want custom routes:
- `/agent/datum/webhooks`
- `/agent/datum/settings`

The prefix reserves namespace for growth.

## Consequences

### Positive
- Clear separation of concerns
- No configuration needed (auto-detection)
- Backward compatible
- Future-proof architecture

### Negative
- URLs less memorable (`/agent/datum` vs `/datum`)
- Extra cognitive overhead
- Less "clean" for marketing/sharing

## Alternatives Considered

1. **Root-level routing** (`agents.ciris.ai/datum`)
   - Rejected: Namespace collisions, breaks mode detection

2. **Subdomain routing** (`datum.agents.ciris.ai`)
   - Rejected: Complex SSL, DNS management per agent

3. **Query parameters** (`agents.ciris.ai?agent=datum`)
   - Rejected: Even worse UX than current approach

## References
- CIRISAgent mode detection: `CIRISGUI/apps/agui/contexts/AgentContextHybrid.tsx`
- CIRISManager routing: `ciris_manager/nginx_manager.py`
- Dual-mode docs: `CIRISGUI/apps/agui/docs/DUAL_MODE_DEPLOYMENT.md`
