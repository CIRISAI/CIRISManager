# Testing Guide for CIRISManager

## Overview

This guide explains the testing approach for CIRISManager. Testing is designed to be simple, fast, and developer-friendly.

## Quick Start

```bash
# Clone and test in under 2 minutes
git clone https://github.com/CIRISAI/ciris-manager.git
cd ciris-manager
./quickstart.sh
```

## Standard Testing Workflow

### 1. Local Development Testing

Standard testing workflow:

```bash
# Set up development environment
make dev

# Run tests
make test

# Run specific test module
pytest tests/ciris_manager/test_manager.py -v

# Run tests with coverage
make test-cov
```

### 2. Testing Standards

Following Python best practices:

- **Simple commands**: `make test` should just work
- **Fast feedback**: Core tests should run in < 30 seconds
- **Clear output**: Failures should be obvious
- **No complex setup**: Virtual env + pip install should be enough

### 3. Test Organization

```
tests/
└── ciris_manager/           # Mirrors source structure
    ├── test_manager.py      # Core manager tests
    ├── test_api_routes.py   # API endpoint tests
    ├── test_auth_*.py       # Authentication tests
    └── test_*.py            # Other component tests
```

**Note**: No `__init__.py` in test directories (pytest best practice)

## Testing Without Docker

Tests handle missing Docker gracefully:

```python
# Tests automatically mock Docker when not available
@pytest.fixture
def mock_docker(monkeypatch):
    """Mock Docker for tests when Docker isn't available."""
    if not docker_available():
        monkeypatch.setattr("docker.from_env", mock_docker_client)
```

## Common Testing Scenarios

### Testing a Bug Fix

```bash
# 1. Create a test that reproduces the bug
echo "def test_bug_reproduction():
    # This should fail before fix
    assert broken_function() == expected" >> tests/ciris_manager/test_bug.py

# 2. Run the test to confirm it fails
pytest tests/ciris_manager/test_bug.py -v

# 3. Fix the bug in the source code

# 4. Run test again to confirm fix
pytest tests/ciris_manager/test_bug.py -v

# 5. Run full test suite
make test
```

### Testing a New Feature

```bash
# 1. Write tests first (TDD approach)
vim tests/ciris_manager/test_new_feature.py

# 2. Run tests (they should fail)
pytest tests/ciris_manager/test_new_feature.py -v

# 3. Implement the feature

# 4. Run tests until they pass
pytest tests/ciris_manager/test_new_feature.py -v -x

# 5. Check coverage
make test-cov
```

### Testing API Changes

```bash
# API tests use FastAPI test client
from fastapi.testclient import TestClient

def test_new_endpoint():
    client = TestClient(app)
    response = client.get("/manager/v1/new-endpoint")
    assert response.status_code == 200
```

## Running Tests

We use pytest directly for all testing needs:

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=ciris_manager

# Run specific test file
pytest tests/ciris_manager/test_manager.py

# Run with verbose output
pytest tests/ -v
```

## Pre-commit Hooks

Ensure code quality before committing:

```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# Run manually
pre-commit run --all-files
```

## CI/CD Integration

Our GitHub Actions run the same tests:

```yaml
# .github/workflows/test.yml
- run: make dev
- run: make test
- run: make lint
```

## Performance Considerations

### Fast Test Execution

- Unit tests should complete in < 10 seconds
- Integration tests in < 30 seconds
- Use `pytest -x` to stop on first failure
- Run specific tests during development

### Test Parallelization

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel
pytest -n auto tests/
```

## Debugging Tests

### Verbose Output

```bash
# Show print statements
pytest -s tests/ciris_manager/test_manager.py

# Show local variables on failure
pytest -l tests/ciris_manager/test_manager.py

# Drop into debugger on failure
pytest --pdb tests/ciris_manager/test_manager.py
```

### Using IDE Debuggers

Most IDEs support pytest debugging:
- VSCode: Python Test Explorer
- PyCharm: Built-in pytest runner
- vim: vim-test plugin

## Test Coverage

### Understanding Coverage Reports

```bash
# Generate HTML coverage report
make test-cov
open htmlcov/index.html

# Coverage goals:
# - New features: 90%+
# - Bug fixes: Must include tests
# - Overall project: 80%+
```

### Excluding Code from Coverage

```python
# pragma: no cover - for code that shouldn't be tested
if TYPE_CHECKING:  # pragma: no cover
    import expensive_module
```

## Testing Best Practices

1. **Write Clear Test Names**
   ```python
   def test_manager_creates_agent_with_valid_template():
       # Not: def test_1() or def test_manager()
   ```

2. **Use Fixtures for Setup**
   ```python
   @pytest.fixture
   def configured_manager():
       return CIRISManager(test_config)
   ```

3. **Test One Thing at a Time**
   ```python
   def test_port_allocation_returns_valid_port():
       # Only test port allocation, not the entire manager
   ```

4. **Mock External Dependencies**
   ```python
   @patch('docker.from_env')
   def test_container_discovery(mock_docker):
       # Don't require actual Docker
   ```

## Getting Help

- Run tests with `-v` for verbose output
- Check `pytest.ini` for configuration
- Read test docstrings for context
- Ask in GitHub Discussions

## Summary

Our testing approach prioritizes:
- **Simplicity**: Easy to understand and run
- **Speed**: Fast feedback loop
- **Clarity**: Clear what's being tested
- **Accessibility**: Works without Docker/complex setup

Remember: Good tests make good contributions! 🚀
