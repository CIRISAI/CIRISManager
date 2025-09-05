# SonarCloud Quality Gate Action Plan

## Current Status
- **Quality Gate**: FAILING ❌
- **Security Rating**: A ✅ (0 vulnerabilities)
- **Reliability Rating**: C ❌ (73 bugs)
- **Security Hotspots**: 39 (0% reviewed) ❌

## Target
Achieve green quality gate by:
1. Fixing bugs to achieve Reliability Rating A (< 1 bug)
2. Reviewing 100% of security hotspots

---

## Phase 1: Critical Bug Fixes (High Priority)
**Goal**: Fix async/sync mismatches causing reliability issues

### 1.1 Async File Operations (15 bugs)
- [ ] Fix `deployment_orchestrator.py` - Replace sync `open()` with `aiofiles`
- [ ] Fix `token_manager.py` - Replace sync file operations
- [ ] Fix `agent_registry.py` - Use async file I/O
- [ ] Fix `version_tracker.py` - Convert to async operations

### 1.2 Task Management (8 bugs)
- [ ] Fix `routes.py` - Save background tasks to prevent GC
- [ ] Fix `telemetry/service.py` - Store task references
- [ ] Fix async task lifecycle management

### 1.3 Subprocess Calls (5 bugs)
- [ ] Fix synchronous `subprocess.run()` in async functions
- [ ] Replace with `asyncio.create_subprocess_exec()`

---

## Phase 2: Security Hotspot Review (Medium Priority)
**Goal**: Review and resolve all 39 hotspots

### 2.1 Quick Wins - Mark as Safe (15 hotspots)
- [ ] Mark localhost HTTP usage as safe (development only)
- [ ] Mark test file HTTP URLs as safe
- [ ] Mark mock OAuth URLs as safe

### 2.2 HTML Security (5 hotspots)
- [ ] Add integrity attributes to CDN resources
- [ ] Add `rel="noopener"` to external links
- [ ] Review and fix CSP headers

### 2.3 Docker Security (2 hotspots)
- [ ] Add USER directive to Dockerfile (non-root)
- [ ] Pin package versions in Dockerfile

### 2.4 File Permissions (7 hotspots)
- [ ] Review `/tmp` usage - mark as safe (temporary files)
- [ ] Validate directory permissions in code

---

## Phase 3: Medium Priority Bugs (30 bugs)
**Goal**: Fix logic and type errors

### 3.1 Floating Point Comparisons (12 bugs)
- [ ] Replace exact equality with `math.isclose()`
- [ ] Use epsilon comparisons in tests

### 3.2 TypeScript Issues (8 bugs)
- [ ] Fix duplicate function names
- [ ] Remove unused instantiations
- [ ] Fix type mismatches

### 3.3 Exception Handling (10 bugs)
- [ ] Properly re-raise `asyncio.CancelledError`
- [ ] Fix exception chains
- [ ] Add proper error context

---

## Phase 4: Low Priority Bugs (20 bugs)
**Goal**: Clean up remaining issues

### 4.1 Code Smell Fixes
- [ ] Remove unreachable code
- [ ] Fix always-true conditions
- [ ] Clean up unused variables

### 4.2 Test Improvements
- [ ] Fix test assertions
- [ ] Remove redundant test code
- [ ] Improve test coverage

---

## Implementation Strategy

### Immediate Actions (This Session)
1. Fix all async file operations in deployment_orchestrator.py
2. Add task tracking to prevent garbage collection
3. Replace sync subprocess calls with async versions
4. Mark obvious false-positive security hotspots
5. Run tests and push fixes

### Follow-up Actions
1. Fix remaining async/sync issues in other files
2. Review and resolve remaining security hotspots
3. Fix floating point comparisons in tests
4. Address TypeScript issues
5. Clean up remaining bugs

---

## Quick Fix Scripts

### Convert sync file operations to async:
```python
# Before
with open(file_path, 'r') as f:
    content = f.read()

# After
import aiofiles
async with aiofiles.open(file_path, 'r') as f:
    content = await f.read()
```

### Fix task garbage collection:
```python
# Before
asyncio.create_task(some_async_function())

# After
self._background_tasks = set()
task = asyncio.create_task(some_async_function())
self._background_tasks.add(task)
task.add_done_callback(self._background_tasks.discard)
```

### Fix floating point comparison:
```python
# Before
assert value == 0.1

# After
import math
assert math.isclose(value, 0.1, rel_tol=1e-9)
```

---

## Validation Checklist
- [ ] All tests pass locally
- [ ] CI/CD pipeline green
- [ ] SonarCloud scan shows:
  - [ ] 0 vulnerabilities
  - [ ] < 1 bug (Reliability Rating A)
  - [ ] 100% security hotspots reviewed
  - [ ] Quality Gate: PASSED

---

## Notes
- Prioritize Phase 1 as it contains the most critical reliability issues
- Security hotspots can be reviewed in parallel with bug fixes
- Many hotspots are false positives that can be quickly marked as safe
- Consider creating a separate PR for each phase for easier review
