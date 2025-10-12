"""
Pytest configuration and fixtures for CIRISManager tests.
"""

import os
import pytest
from unittest.mock import Mock, patch


def pytest_configure(config):
    """
    Set environment variables before any test modules are imported.
    This runs very early in the pytest lifecycle.
    """
    os.environ["DISABLE_RATE_LIMIT"] = "true"
    os.environ["CIRIS_TEST_MODE"] = "true"
    os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing"
    os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars-long"


@pytest.fixture
def mock_docker_client():
    """Mock Docker client for tests."""
    with patch("docker.from_env") as mock_docker:
        client = Mock()
        mock_docker.return_value = client
        yield client


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for testing."""
    dirs = {
        "agents": tmp_path / "agents",
        "templates": tmp_path / "templates",
        "config": tmp_path / "config",
        "nginx": tmp_path / "nginx",
    }

    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)

    return dirs
