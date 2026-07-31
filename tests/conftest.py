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


@pytest.fixture(autouse=True)
def _isolate_environ():
    """Snapshot and restore os.environ around every test.

    Several tests mutate os.environ directly instead of using monkeypatch, and
    the mutations leaked into whatever ran next. Concretely: test_cd_api_endpoints
    set CIRIS_DEPLOY_TOKEN="test-deploy-token" (17 chars) with no cleanup, and
    test_deployment_tokens::test_save_runs_when_tokens_generated then asserted
    every generated token was >20 chars - so it failed depending only on test
    ORDER. It passed under `pytest -n 4` because xdist happened to schedule the
    two files on different workers, and failed in a serial run. That is a green
    CI that proves nothing about the next scheduling change.

    Restoring here fixes the whole class of bug at once, including future ones,
    rather than chasing individual call sites. Tests that genuinely need an env
    var should still prefer monkeypatch.setenv for clarity.
    """
    original = os.environ.copy()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


@pytest.fixture(autouse=True)
def _no_host_port_probing():
    """Stop port allocation from depending on the host's real sockets.

    `PortManager.allocate_port` calls `_is_port_in_use`, which opens a socket
    against the machine running the tests. If anything happens to be listening
    on a port in the configured range, allocation silently skips it - so tests
    asserting `port == 8080` fail depending on what else is running on the box.

    That produced a genuine heisenbug: the same test failed repeatedly while
    something held 8080 locally, then passed six times in a row once the port
    was released, and was reproducible on demand by binding 8080. On a CI
    runner it is a coin flip.

    Unit tests should exercise allocation bookkeeping, not the host's network
    state, so the probe always reports "free" here. A test that specifically
    wants the real probe can patch it back.
    """
    from ciris_manager.port_manager import PortManager

    with patch.object(PortManager, "_is_port_in_use", return_value=False):
        yield


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """Clear process-global caches between tests.

    These live at module scope, so under both serial runs and xdist (where a
    worker runs many tests in one process) they carry state from one test into
    the next. Each is a genuine cross-test hazard:

    - `crypto._token_encryption` is derived from MANAGER_JWT_SECRET /
      CIRIS_ENCRYPTION_SALT at first use. Now that `_isolate_environ` restores
      those per test, a cached instance would be keyed to another test's
      secrets - so it MUST be dropped alongside the env reset.
    - `multi_server_docker._server_failures` is circuit-breaker state. One test
      tripping a breaker leaves later tests believing a server is down.
    - `docker_discovery._discovery_cache` has a 30s TTL, comfortably longer
      than a test run, so cached agent lists leak between tests.
    - `device_auth_routes._device_codes` / `_user_codes` are in-flight auth
      state that should never span tests.

    Cleared before AND after: a module imported mid-session can populate its
    cache during collection, so clearing only on teardown still leaves the
    first test in a run reading someone else's state.
    """

    def _clear():
        try:
            from ciris_manager import crypto

            crypto._token_encryption = None
        except Exception:
            pass
        try:
            from ciris_manager import multi_server_docker

            multi_server_docker._server_failures.clear()
        except Exception:
            pass
        try:
            from ciris_manager import docker_discovery

            docker_discovery._discovery_cache.clear()
        except Exception:
            pass
        try:
            from ciris_manager.api import device_auth_routes

            device_auth_routes._device_codes.clear()
            device_auth_routes._user_codes.clear()
        except Exception:
            pass

    _clear()
    try:
        yield
    finally:
        _clear()


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
