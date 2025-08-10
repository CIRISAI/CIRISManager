"""
Pytest configuration and fixtures for CIRISManager tests.
"""

import pytest
from unittest.mock import Mock, patch
import os


@pytest.fixture(autouse=True)
def disable_rate_limiting():
    """Automatically disable rate limiting for all tests."""
    # Mock the SLOWAPI_AVAILABLE flag to False
    with patch("ciris_manager.api.rate_limit.SLOWAPI_AVAILABLE", False):
        with patch("ciris_manager.api.rate_limit.limiter", None):
            # Also patch the decorators to be no-ops
            with patch("ciris_manager.api.rate_limit.auth_limit", lambda f: f):
                with patch("ciris_manager.api.rate_limit.login_limit", lambda f: f):
                    with patch("ciris_manager.api.rate_limit.create_limit", lambda f: f):
                        with patch("ciris_manager.api.rate_limit.read_limit", lambda f: f):
                            with patch("ciris_manager.api.rate_limit.deploy_limit", lambda f: f):
                                yield


@pytest.fixture(autouse=True)
def set_test_environment():
    """Set environment variables for testing."""
    old_env = os.environ.copy()

    # Set test environment variables
    os.environ["CIRIS_TEST_MODE"] = "true"
    os.environ["MANAGER_JWT_SECRET"] = "test-secret-key-for-testing"
    os.environ["CIRIS_ENCRYPTION_SALT"] = "test-salt-sixteen-chars-long"

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(old_env)


@pytest.fixture
def mock_docker_client():
    """Mock Docker client for tests."""
    with patch("docker.from_env") as mock_docker:
        client = Mock()
        mock_docker.return_value = client
        yield client
