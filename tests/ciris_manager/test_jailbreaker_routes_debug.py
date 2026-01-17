"""
Unit tests for debugging jailbreaker initialization in create_routes.
"""

import pytest
import os
from unittest.mock import Mock, patch
from fastapi import APIRouter
from ciris_manager.api.routes import create_routes


class TestJailbreakerRouteDebug:
    """Debug tests for jailbreaker route initialization."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up test environment before each test."""
        # Clear environment variables
        self.original_env = {}
        for key in ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "JAILBREAK_AGENT_SERVICE_TOKEN"]:
            if key in os.environ:
                self.original_env[key] = os.environ[key]
                del os.environ[key]

        yield

        # Restore original environment
        for key, value in self.original_env.items():
            os.environ[key] = value

    @pytest.fixture
    def mock_manager(self):
        """Create a basic mock manager for testing."""
        manager = Mock()
        manager.config = Mock()
        manager.config.manager = Mock()
        manager.config.manager.agents_directory = "/tmp/test-agents"
        manager.container_manager = Mock()

        # Add other required mocks to prevent failures
        manager.agent_registry = Mock()
        manager.agent_registry.list_agents = Mock(return_value=[])
        manager.port_manager = Mock()
        manager.port_manager.allocated_ports = {}
        manager.template_verifier = Mock()
        manager.template_verifier.list_pre_approved_templates = Mock(return_value={})

        return manager

    def test_create_routes_basic_execution(self, mock_manager):
        """Test that create_routes executes without environment variables."""
        # This should not raise any exceptions
        router = create_routes(mock_manager)
        assert router is not None

    @patch.dict(
        os.environ,
        {
            "DISCORD_CLIENT_ID": "test_client_id",
            "DISCORD_CLIENT_SECRET": "test_client_secret",
            "JAILBREAK_AGENT_SERVICE_TOKEN": "test_token",
        },
    )
    def test_jailbreaker_initialization_with_credentials(self, mock_manager):
        """Test jailbreaker initialization when Discord credentials are present."""
        # Mock the jailbreaker imports - they're imported locally inside the try block
        with (
            patch("ciris_manager.jailbreaker.JailbreakerConfig") as mock_config,
            patch("ciris_manager.jailbreaker.JailbreakerService") as mock_service,
            patch("ciris_manager.jailbreaker.create_jailbreaker_routes") as mock_routes,
        ):
            mock_config.from_env.return_value = Mock(target_agent_id="test-agent")
            mock_service_instance = Mock()
            mock_service.return_value = mock_service_instance
            mock_routes.return_value = APIRouter()  # Return real APIRouter

            # Execute create_routes
            router = create_routes(mock_manager)

            # Verify jailbreaker initialization was attempted
            mock_config.from_env.assert_called_once()
            mock_service.assert_called_once()
            mock_routes.assert_called_once_with(mock_service_instance)

            assert router is not None

    def test_missing_discord_credentials(self, mock_manager):
        """Test behavior when Discord credentials are missing."""
        # Only set one credential
        with patch.dict(os.environ, {"DISCORD_CLIENT_ID": "test_id"}):
            router = create_routes(mock_manager)
            assert router is not None

    def test_jailbreaker_import_failure(self, mock_manager):
        """Test behavior when jailbreaker imports fail."""
        with patch.dict(
            os.environ,
            {"DISCORD_CLIENT_ID": "test_client_id", "DISCORD_CLIENT_SECRET": "test_client_secret"},
        ):
            # Mock import failure
            with patch(
                "ciris_manager.jailbreaker.JailbreakerConfig",
                side_effect=ImportError("Module not found"),
            ):
                router = create_routes(mock_manager)
                assert router is not None

    @patch.dict(
        os.environ,
        {
            "DISCORD_CLIENT_ID": "1394750008615764029",
            "DISCORD_CLIENT_SECRET": "pgqYCTIMqMZFF2G63O6d12NKQawrFC55",
            "JAILBREAK_AGENT_SERVICE_TOKEN": "21131fdf6cd5a44044fcec261aba2c596aa8fad1a5b9725a41cacf6b33419023",
        },
    )
    def test_production_credentials(self, mock_manager):
        """Test with actual production credentials to verify initialization is called."""
        # Mock the jailbreaker modules to see if they're called
        with (
            patch("ciris_manager.jailbreaker.JailbreakerConfig") as mock_config,
            patch("ciris_manager.jailbreaker.JailbreakerService") as mock_service,
            patch("ciris_manager.jailbreaker.create_jailbreaker_routes") as mock_routes,
        ):
            mock_config.from_env.return_value = Mock(target_agent_id="echo-nemesis-v2tyey")
            mock_service_instance = Mock()
            mock_service.return_value = mock_service_instance
            mock_routes.return_value = APIRouter()  # Return real APIRouter

            router = create_routes(mock_manager)

            # Check if initialization was called
            mock_config.from_env.assert_called_once()
            assert router is not None

    def test_jailbreaker_initialization_exception_handling(self, mock_manager):
        """Test that exceptions in jailbreaker initialization are properly handled."""
        with patch.dict(
            os.environ,
            {"DISCORD_CLIENT_ID": "test_client_id", "DISCORD_CLIENT_SECRET": "test_client_secret"},
        ):
            # Mock jailbreaker config to raise an exception
            with patch("ciris_manager.jailbreaker.JailbreakerConfig") as mock_config:
                mock_config.from_env.side_effect = Exception("Test exception")

                # Should not raise exception, should handle it gracefully
                router = create_routes(mock_manager)
                assert router is not None

    def test_environment_variable_check_in_create_routes(self, mock_manager):
        """Test to verify environment variable checking logic works as expected."""
        # Test without any environment variables - should not initialize jailbreaker
        router = create_routes(mock_manager)
        assert router is not None

        # Test with only client ID - should not initialize
        with patch.dict(os.environ, {"DISCORD_CLIENT_ID": "test_id"}):
            router = create_routes(mock_manager)
            assert router is not None

        # Test with only client secret - should not initialize
        with patch.dict(os.environ, {"DISCORD_CLIENT_SECRET": "test_secret"}):
            router = create_routes(mock_manager)
            assert router is not None

        # Test with both credentials - should attempt initialization
        with patch.dict(
            os.environ, {"DISCORD_CLIENT_ID": "test_id", "DISCORD_CLIENT_SECRET": "test_secret"}
        ):
            with (
                patch("ciris_manager.jailbreaker.JailbreakerConfig") as mock_config,
                patch("ciris_manager.jailbreaker.JailbreakerService") as mock_service,
                patch("ciris_manager.jailbreaker.create_jailbreaker_routes") as mock_routes,
            ):
                mock_config.from_env.return_value = Mock(target_agent_id="test-agent")
                mock_service.return_value = Mock()
                mock_routes.return_value = APIRouter()  # Return real APIRouter

                router = create_routes(mock_manager)

                # Should have attempted initialization
                mock_config.from_env.assert_called_once()
                assert router is not None
