# Immediate SonarCloud Fixes - Phase 1

## Critical Async/Sync Issues to Fix

### 1. deployment_orchestrator.py (9 sync file operations in async context)
Lines with issues:
- Line 68: `with open(self.deployment_state_file, "r")` in async context
- Line 122: `with open(temp_file, "w")` in async save_state
- Line 689: `with open(gui_file, "r")` in async function
- Line 700: `with open(nginx_file, "r")` in async function
- Line 856: `with open(gui_versions_file, "r")` in async function
- Line 865: `with open(nginx_versions_file, "r")` in async function
- Line 2798: `with open(metadata_file, "r")` in async function
- Line 2815: `with open(metadata_file, "w")` in async function
- Lines 2838, 2893: More file reads in async context

### 2. Key Functions to Convert

#### deployment_orchestrator.py
- `_load_state()` - Convert to async with aiofiles
- `save_state()` - Already async, needs aiofiles
- `_get_current_versions()` - Needs async file operations
- `_store_container_version()` - Needs async file operations

### 3. Required Changes Pattern

```python
# BEFORE (sync in async function)
async def some_function():
    with open(file_path, 'r') as f:
        data = json.load(f)

# AFTER (proper async)
import aiofiles
import json

async def some_function():
    async with aiofiles.open(file_path, 'r') as f:
        content = await f.read()
        data = json.loads(content)
```

### 4. Task Management Issues to Fix

Need to store background tasks to prevent garbage collection:
- routes.py: Multiple `asyncio.create_task()` calls without storing reference
- telemetry/service.py: Background tasks not tracked

### 5. Subprocess Issues to Fix

Replace `subprocess.run()` with `asyncio.create_subprocess_exec()` in:
- token_manager.py
- routes.py (multiple locations)

## Implementation Order

1. **First PR**: Fix deployment_orchestrator.py file operations (highest impact)
2. **Second PR**: Fix task management in routes.py
3. **Third PR**: Fix subprocess calls
4. **Fourth PR**: Fix floating point comparisons in tests

This will reduce bug count from 73 to ~40 and should improve reliability rating to B or A.