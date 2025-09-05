# CIRISManager Version Display Task

## Overview
CIRIS agents now expose version information through their API. CIRISManager should query and display this information for better visibility into deployed agent versions.

## What's Been Added to CIRIS Agents

### 1. Version Constants
Location: `ciris_engine/constants.py`
```python
CIRIS_VERSION = "1.0.4-beta"
CIRIS_VERSION_MAJOR = 1
CIRIS_VERSION_MINOR = 0
CIRIS_VERSION_PATCH = 4
CIRIS_VERSION_STAGE = "beta"
CIRIS_CODENAME = "Graceful Guardian"
```

### 2. SystemSnapshot Enhancement
The SystemSnapshot now includes:
- `agent_version`: The semantic version (e.g., "1.0.4-beta")
- `agent_codename`: The release codename (e.g., "Graceful Guardian")
- `agent_code_hash`: The code hash for exact version identification

### 3. API Endpoint Enhancement
The `/v1/agent/status` endpoint now returns:
```json
{
  "agent_id": "datum",
  "name": "Datum",
  "version": "1.0.4-beta",
  "codename": "Graceful Guardian",
  "code_hash": "a1b2c3d4e5f6",
  "cognitive_state": "WORK",
  "uptime_seconds": 3600,
  ...
}
```

### 4. GUI Updates
The CIRISGUI dashboard now displays:
- Version in the header next to the title
- Detailed version card showing version, codename, and code hash

## Task for CIRISManager

### 1. Query Agent Versions
- When listing agents, call each agent's `/v1/agent/status` endpoint
- Extract the `version`, `codename`, and `code_hash` fields
- Handle cases where older agents might not have these fields

### 2. Display in Manager UI
Add version information to:
- Agent list/table view - show version as a column
- Agent detail view - show full version details
- Dashboard overview - show version distribution across agents

### 3. Version Tracking Features
Consider adding:
- Version mismatch warnings (if agents are on different versions)
- Update available notifications (when newer version detected)
- Version history tracking (store version changes over time)

### 4. API Endpoint
Add a manager endpoint that aggregates version info:
```
GET /manager/v1/agents/versions
```
Returns:
```json
{
  "agents": [
    {
      "agent_id": "datum",
      "version": "1.0.4-beta",
      "codename": "Graceful Guardian",
      "code_hash": "a1b2c3d4e5f6"
    },
    ...
  ],
  "version_summary": {
    "1.0.4-beta": 3,
    "1.0.3-beta": 1
  }
}
```

## Implementation Notes

1. **Graceful Degradation**: Handle agents that don't have version info (older versions)
2. **Caching**: Cache version info since it doesn't change frequently
3. **Error Handling**: If agent is down, show last known version
4. **Visual Design**: Use badges or tags to make versions visually distinct

## Benefits

1. **Deployment Visibility**: Know exactly which version each agent is running
2. **Update Management**: Identify agents that need updates
3. **Debugging**: Version info helps when troubleshooting issues
4. **Compliance**: Track version deployments for audit purposes

## Priority
Medium - This is a quality of life improvement that enhances operational visibility but isn't critical for functionality.
