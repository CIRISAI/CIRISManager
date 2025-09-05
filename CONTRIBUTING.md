# Contributing to CIRISManager

Thank you for your interest in contributing to CIRISManager! This guide will help you get started.

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Docker (for testing container management features)
- Git

### Setting Up Your Development Environment

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/ciris-manager.git
   cd ciris-manager
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install development dependencies:**
   ```bash
   make dev
   # Or if you don't have make:
   pip install -e ".[dev]"
   ```

4. **Run tests to verify setup:**
   ```bash
   make test
   ```

## Development Workflow

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
pytest tests/ciris_manager/test_manager.py -v

# Run specific test
pytest tests/ciris_manager/test_manager.py::test_manager_initialization -v
```

### Code Quality

Before submitting a PR, ensure your code passes all quality checks:

```bash
# Format code
make format

# Run linters
make lint
```

### Running Locally

```bash
# Run the API server only
make run-api

# Run the full manager (requires config.yml)
cp config.example.yml config.yml
make run
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
```

### 2. Make Your Changes

- Write clean, readable code
- Follow existing code style
- Add tests for new functionality
- Update documentation as needed

### 3. Commit Guidelines

We follow conventional commits:

```bash
# Feature
git commit -m "feat: add new agent template system"

# Bug fix
git commit -m "fix: correct port allocation race condition"

# Documentation
git commit -m "docs: update API endpoints documentation"

# Tests
git commit -m "test: add coverage for crash loop detection"
```

### 4. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Code Style

- We use [Ruff](https://docs.astral.sh/ruff/) for both formatting and linting
- Python 3.11+ type hints are required for new code
- Docstrings should follow Google style
- Line length: 100 characters
- All code must pass `ruff check` and `ruff format`

## Testing Guidelines

### Writing Tests

- Tests go in `tests/` mirroring the source structure
- Use pytest fixtures for common setup
- Mock external dependencies (Docker, network calls)
- Aim for 80%+ code coverage

Example test:

```python
import pytest
from ciris_manager.manager import CIRISManager

@pytest.fixture
def manager():
    """Create a test manager instance."""
    return CIRISManager()

def test_manager_initialization(manager):
    """Test that manager initializes correctly."""
    assert manager is not None
    assert manager.config is not None
```

### Async Tests

For async code, use `pytest-asyncio`:

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected_value
```

## Project Structure

```
ciris-manager/
├── ciris_manager/         # Main package
│   ├── api/              # FastAPI routes and auth
│   ├── core/             # Core functionality
│   ├── config/           # Configuration management
│   └── utils/            # Utility functions
├── tests/                # Test suite
├── deployment/           # Deployment scripts
├── deployment/           # Deployment scripts (continued)
└── docs/                 # Documentation
```

## Common Tasks

### Adding a New API Endpoint

1. Add route in `ciris_manager/api/routes.py`
2. Add tests in `tests/ciris_manager/test_api_routes.py`
3. Update API documentation

### Adding a New Manager Feature

1. Implement in appropriate module
2. Add unit tests
3. Add integration test if needed
4. Update CLAUDE.md if it affects AI assistance

## Getting Help

- Check existing issues and PRs
- Join our Discord: [link]
- Read the [documentation](docs/)
- Ask questions in GitHub Discussions

## Pull Request Process

1. **Before submitting:**
   - Run `make test` - all tests must pass
   - Run `make lint` - no linting errors
   - Update documentation if needed

2. **PR Description:**
   - Describe what changes you made
   - Reference any related issues
   - Include screenshots for UI changes
   - List any breaking changes

3. **Review Process:**
   - A maintainer will review your PR
   - Address any feedback
   - Once approved, it will be merged

## Reporting Issues

When reporting issues, please include:

- Python version
- OS and version
- Docker version
- Steps to reproduce
- Expected vs actual behavior
- Any error messages

## Security

If you find a security vulnerability, please email security@ciris.ai instead of creating a public issue.

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## Thank You!

Your contributions make CIRISManager better for everyone. We appreciate your time and effort! 🎉
