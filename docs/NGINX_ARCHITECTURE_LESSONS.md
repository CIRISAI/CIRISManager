# Nginx Architecture: Lessons Learned

## The Journey from Complexity to Simplicity

This document captures the hard-won lessons from evolving our nginx configuration management from a complex dual-config system to a simple, single-file approach.

## Core Principle: One File, One Process, One Truth

**What we learned**: Managing nginx configuration should be dead simple.

### The Final Architecture

```
CIRISManager writes → /home/ciris/nginx/nginx.conf → Nginx container reads
```

That's it. One file, one writer, one reader.

## Why No Partial Configs or Includes

**The Failed Approach**:
- Static config with infrastructure routes
- Dynamic config with agent routes
- Include directive to combine them
- Two volume mounts in docker-compose

**Why It Failed**:
1. **Debugging nightmare** - Which file has the problem route?
2. **Route conflicts** - Both files loaded independently, routes could overlap
3. **Complexity cascade** - Migration scripts, dual loading fixes, more complexity
4. **Mental overhead** - Everyone had to understand the include relationship

**The Simple Solution**:
- One nginx.conf with everything
- Regenerate the whole file when anything changes
- Clear, complete, debuggable

## Why No Default Routes

**The Failed Pattern**: `/v1/*` → default agent (usually 'datum')

**Why It's Wrong**:
1. **Ambiguity** - Which agent is "default"? Changes per deployment
2. **Hidden coupling** - Code using `/v1/` breaks when default changes
3. **Testing issues** - Can't test multi-agent scenarios properly
4. **OAuth confusion** - Callback URLs become ambiguous
5. **Documentation lies** - Examples show `/v1/` but don't say which agent

**The Right Way**:
- Every API call specifies the agent: `/api/{agent_id}/v1/*`
- Explicit is better than implicit
- Works identically with 0, 1, or 100 agents

## Why Manager GUI Uses Static Files

**The Failed Temptation**: Another React container for the Manager GUI

**Why Static Files Win**:
1. **Zero containers** - Nginx already running, just serve files
2. **Instant updates** - Change file, reload page, done
3. **No build process** - Edit HTML/JS/CSS directly
4. **Debuggable** - View source shows exactly what's running
5. **Fast deployment** - No container builds, no npm installs

**Implementation**:
```
/home/ciris/CIRISManager/static/
├── index.html
├── app.js
└── style.css
```

Served directly by nginx at `/`.

## Why Infrastructure Must Be Separate from Application

**The Confusion**: Should nginx live with agents or manager?

**The Answer**: Infrastructure (routing) belongs to the infrastructure layer (Manager).

**Clean Separation**:
- **CIRISManager owns**: Nginx, routing, infrastructure concerns
- **CIRISAgent owns**: Agent containers, agent logic, agent GUI

**Benefits**:
1. Agents don't know about routing
2. Manager can adopt any agent
3. Clear ownership and responsibilities
4. No circular dependencies

## The Container Count Formula

**Simple Math**:
- N agents = N containers
- 1 GUI container (multi-tenant, from CIRISAgent)
- 1 nginx container (from CIRISManager)
- 0 manager GUI containers (static files)

Total: N + 2 containers

**Why This Matters**: Every container adds complexity. We minimize containers while maintaining clean separation.

## Configuration Path Consistency

**The Lesson**: Use the same paths in dev and production.

**Bad**:
- Dev: `/opt/ciris-manager/nginx/`
- Prod: `/home/ciris/nginx/`
- Result: Different configs, different bugs

**Good**:
- Everywhere: `/home/ciris/nginx/nginx.conf`
- Result: What works in dev works in prod

## The Value of Saying No

Things we explicitly don't support:
- Custom URL paths (no `/my/custom/ciris/agent/`)
- Partial config generation
- Multiple nginx configs
- Default routes
- Clever routing tricks

**Why**: Every feature adds complexity. Complexity kills maintainability.

## Testing What Matters

**Don't Test**: nginx syntax (nginx -t does that)
**Do Test**:
- Routes exist for each agent
- No default routes sneak in
- Manager GUI accessible at `/`
- Agent GUI accessible at `/agent/{id}`

## The Ultimate Test

Can you explain the entire routing architecture in one paragraph?

**Yes**: Nginx reads one config file that CIRISManager writes. This config routes `/` to Manager GUI (static files), `/agent/{id}` to Agent GUI (container), `/manager/v1/*` to Manager API, and `/api/{id}/v1/*` to specific agent APIs. No defaults, no includes, no complexity.

If you can't explain it simply, it's too complex.

## Remember

- Clever is the enemy of maintainable
- One file is better than two with includes
- Explicit routes are better than implicit defaults
- Static files are better than another container
- Simple explanations indicate simple architectures

When in doubt, choose the boring solution. It will still work in 5 years.
