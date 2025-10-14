# MyPy Type Error Fixing Plan

**Goal**: Achieve 100% mypy compliance (0 errors) in CIRISManager

**Current Status**: 30 errors in 6 files

---

## Error Categories

### Category 1: Missing Library Stubs (2 errors)
**Files**: `utils.py:19`, `inspect.py:16`

**Problem**: Missing type stubs for `paramiko` and `tabulate`

**Solution**:
```bash
pip install types-paramiko types-tabulate
```

**Estimated Time**: 1 minute

---

### Category 2: Returning Any from Typed Functions (14 errors)

#### 2A. CLI Utils (4 errors)
**File**: `ciris_manager/cli/utils.py`
**Lines**: 161, 163, 171, 177

**Problem**: Functions declared to return `dict[str, Any]` but actually return `Any` from SDK client methods

**Root Cause**: The SDK client methods (`list_agents()`, `get_agent()`, etc.) have no type annotations

**Solution**:
1. Create proper Protocol definitions in `protocols.py` for SDK client methods
2. Add return type annotations to SDK client interface
3. Cast SDK responses to typed dicts where necessary

**Code Pattern**:
```python
# Current (returns Any):
def get_agent_info(client, agent_id: str) -> dict[str, Any]:
    return client.get_agent(agent_id)  # SDK returns Any

# Fixed:
def get_agent_info(client: CIRISClient, agent_id: str) -> dict[str, Any]:
    result = client.get_agent(agent_id)
    return cast(dict[str, Any], result)
```

**Estimated Time**: 30 minutes

#### 2B. CLI Output (1 error)
**File**: `ciris_manager/cli/output.py`
**Line**: 68

**Problem**: `format_table()` returns Any from `tabulate()` function

**Solution**: Cast tabulate result to str
```python
from typing import cast
return cast(str, tabulate(table_data, headers=headers, tablefmt=tablefmt))
```

**Estimated Time**: 5 minutes

#### 2C. CLI Config Commands (4 errors)
**File**: `ciris_manager/cli/commands/config.py`
**Lines**: 49, 54, 63, 68

**Problem**: Functions return Any from SDK client methods

**Solution**: Same as 2A - add type casts
```python
def get_config(client: CIRISClient, agent_id: str) -> dict[str, Any]:
    result = client.get_agent_config(agent_id)
    return cast(dict[str, Any], result)
```

**Estimated Time**: 15 minutes

#### 2D. CLI Inspect Commands (1 error)
**File**: `ciris_manager/cli/commands/inspect.py`
**Line**: 210

**Problem**: `json.loads()` returns Any

**Solution**: Cast to dict[str, str]
```python
labels = json.loads(result.stdout.strip())
return cast(dict[str, str], labels)
```

**Estimated Time**: 5 minutes

#### 2E. CLI Main (3 errors)
**File**: `ciris_manager/cli/main.py`
**Lines**: 341, 355, 369

**Problem**: Command handlers return Any (should return int exit codes)

**Solution**: Add explicit int() casts or type annotations
```python
return int(result) if result is not None else 0
```

**Estimated Time**: 10 minutes

#### 2F. Deployment Orchestrator (2 errors)
**File**: `ciris_manager/deployment_orchestrator.py`
**Lines**: 1112, 1958

**Problem**: Returning Any from dict.get() operations

**Solution**: Add type casts or default values
```python
# Line 1112 (returns str):
return cast(str, some_dict.get("key", "default"))

# Line 1958 (returns bool):
return cast(bool, some_dict.get("key", False))
```

**Estimated Time**: 10 minutes

---

### Category 3: Missing Type Annotations (1 error)
**File**: `ciris_manager/cli/output.py`
**Line**: 38

**Problem**: Variable `all_keys` needs type annotation

**Solution**:
```python
all_keys: set[str] = set()
```

**Estimated Time**: 2 minutes

---

### Category 4: Index Operations on Object Type (10 errors)
**File**: `ciris_manager/cli/commands/inspect.py`
**Lines**: 469, 484, 488, 490, 492, 504-506

**Problem**: Variables typed as `object` but used as dict[str, Any]

**Root Cause**: The `results` variable is declared as `Dict[str, Any]` but mypy loses track of the type

**Solution**: Add explicit type annotations at variable assignment
```python
# Current:
results: Dict[str, Any] = {...}
results["checks"] = {}  # mypy thinks results is object

# Fixed:
results: Dict[str, Any] = {...}
checks: Dict[str, Any] = {}
results["checks"] = checks
```

**Estimated Time**: 20 minutes

---

### Category 5: Untyped Function Bodies (3 notes)
**File**: `ciris_manager/api/migration_helpers.py`
**Lines**: 202-204

**Problem**: Functions have no type annotations, mypy skips checking bodies

**Solution**: Add type annotations to migration helper functions
```python
# Current:
def migrate_something(data):
    pass

# Fixed:
def migrate_something(data: dict[str, Any]) -> dict[str, Any]:
    pass
```

**Estimated Time**: 15 minutes

---

## Execution Plan

### Phase 1: Quick Wins (10 minutes)
1. Install missing stubs: `pip install types-paramiko types-tabulate`
2. Fix missing type annotation in output.py:38
3. Add casts to output.py:68 for tabulate result
4. Fix inspect.py:210 json.loads cast

### Phase 2: SDK Client Protocol (30 minutes)
1. Update `protocols.py` with proper SDK client return types
2. Add type casts in utils.py (lines 161, 163, 171, 177)
3. Add type casts in config.py (lines 49, 54, 63, 68)

### Phase 3: Index Operations (20 minutes)
1. Fix inspect.py index operations by restructuring variable assignments
2. Add explicit type hints for nested dict operations

### Phase 4: Exit Code Returns (10 minutes)
1. Fix main.py return statements (lines 341, 355, 369)
2. Add int() casts where needed

### Phase 5: Deployment Orchestrator (10 minutes)
1. Fix deployment_orchestrator.py line 1112 (str return)
2. Fix deployment_orchestrator.py line 1958 (bool return)

### Phase 6: Migration Helpers (15 minutes)
1. Add type annotations to migration_helpers.py functions

### Phase 7: Verification (5 minutes)
1. Run `mypy ciris_manager/` - should show 0 errors
2. Run `pytest` - ensure no regressions
3. Run `ruff check` - ensure no new linting issues

---

## Total Estimated Time: ~2 hours

## Dependencies
- types-paramiko
- types-tabulate

## Testing Strategy
After each phase:
1. Run mypy to verify error count decreased
2. Run relevant unit tests
3. Commit changes with descriptive message

## Rollback Plan
- Each phase is independent
- Can revert individual commits if issues arise
- Keep main branch stable

---

## Next Steps After Type Fixes
1. Fix remaining 7 ruff linting errors
2. Fix test failure in `test_deployment_aborts_on_explorer_failure`
3. Deploy remote scout agent
4. Validate nginx and OAuth configurations
