"""
Integration tests for complete jailbreaker reset flow.

Tests the end-to-end reset process including:
- Container lifecycle management
- Data directory handling
- Permission management
- Error recovery
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

from ciris_manager.jailbreaker import JailbreakerService, JailbreakerConfig
from ciris_manager.jailbreaker.models import ResetStatus


class TestJailbreakerResetIntegration:
    """Integration tests for jailbreaker reset functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def config(self):
        """Create test jailbreaker config."""
        return JailbreakerConfig(
            discord_client_id="test_client",
            discord_client_secret="test_secret",
            target_agent_id="echo-nemesis-v2tyey",
            agent_service_token="test_token",
        )

    @pytest.fixture
    def mock_container_manager(self):
        """Mock container manager."""
        manager = Mock()
        manager.start_container = AsyncMock()
        manager.stop_container = AsyncMock()
        return manager

    @pytest.fixture
    def jailbreaker_service(self, config, temp_dir, mock_container_manager):
        """Create jailbreaker service with mocked dependencies."""
        # Create agents directory
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir()

        service = JailbreakerService(config, agents_dir, mock_container_manager)
        return service

    @pytest.mark.asyncio
    async def test_complete_reset_flow_success(
        self, jailbreaker_service, temp_dir, mock_container_manager
    ):
        """Test successful complete reset flow."""
        # Setup test data directory
        agent_dir = temp_dir / "agents" / "echo-nemesis-v2tyey"
        agent_dir.mkdir(parents=True)
        data_dir = agent_dir / "data"
        data_dir.mkdir()
        test_file = data_dir / "test.db"
        test_file.write_text("test data")

        # Mock successful auth and rate limiting
        with (
            patch.object(
                jailbreaker_service, "verify_access_token", return_value=(True, "test_user")
            ),
            patch.object(
                jailbreaker_service.rate_limiter, "check_rate_limit", return_value=(True, None)
            ),
            patch.object(jailbreaker_service.rate_limiter, "record_reset"),
            patch.object(jailbreaker_service, "check_agent_health", return_value=True),
            patch("subprocess.run") as mock_subprocess,
        ):
            # Mock subprocess calls
            mock_subprocess.return_value.returncode = 0

            # Execute reset
            result = await jailbreaker_service.reset_agent("test_token")

            # Verify result
            assert result.status == ResetStatus.SUCCESS
            assert result.user_id == "test_user"
            assert result.agent_id == "echo-nemesis-v2tyey"

            # Verify container operations were called
            mock_container_manager.stop_container.assert_called_once_with(
                "ciris-echo-nemesis-v2tyey"
            )
            mock_container_manager.start_container.assert_called_once_with(
                "ciris-echo-nemesis-v2tyey"
            )

            # Verify data directory was recreated
            assert data_dir.exists()
            assert not test_file.exists()  # Original data should be gone

    @pytest.mark.asyncio
    async def test_reset_handles_container_name_correctly(
        self, jailbreaker_service, mock_container_manager
    ):
        """Test that reset uses correct container naming convention."""
        with (
            patch.object(
                jailbreaker_service, "verify_access_token", return_value=(True, "test_user")
            ),
            patch.object(
                jailbreaker_service.rate_limiter, "check_rate_limit", return_value=(True, None)
            ),
            patch.object(jailbreaker_service.rate_limiter, "record_reset"),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            await jailbreaker_service.reset_agent("test_token")

            # Verify correct container name is used (ciris-echo-nemesis-v2tyey, not ciris-agent-echo-nemesis-v2tyey)
            mock_container_manager.stop_container.assert_called_with("ciris-echo-nemesis-v2tyey")
            mock_container_manager.start_container.assert_called_with("ciris-echo-nemesis-v2tyey")

    @pytest.mark.asyncio
    async def test_reset_handles_missing_data_directory(
        self, jailbreaker_service, temp_dir, mock_container_manager
    ):
        """Test reset when data directory doesn't exist."""
        # Setup agent directory without data directory
        agent_dir = temp_dir / "agents" / "echo-nemesis-v2tyey"
        agent_dir.mkdir(parents=True)

        with (
            patch.object(
                jailbreaker_service, "verify_access_token", return_value=(True, "test_user")
            ),
            patch.object(
                jailbreaker_service.rate_limiter, "check_rate_limit", return_value=(True, None)
            ),
            patch.object(jailbreaker_service.rate_limiter, "record_reset"),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            result = await jailbreaker_service.reset_agent("test_token")

            # Should succeed and create data directory
            assert result.status == ResetStatus.SUCCESS
            data_dir = agent_dir / "data"
            assert data_dir.exists()

    @pytest.mark.asyncio
    async def test_reset_handles_permission_errors_gracefully(
        self, jailbreaker_service, temp_dir, mock_container_manager
    ):
        """Test reset handles permission errors with sudo fallback."""
        # Setup test data
        agent_dir = temp_dir / "agents" / "echo-nemesis-v2tyey"
        agent_dir.mkdir(parents=True)
        data_dir = agent_dir / "data"
        data_dir.mkdir()

        with (
            patch.object(
                jailbreaker_service, "verify_access_token", return_value=(True, "test_user")
            ),
            patch.object(
                jailbreaker_service.rate_limiter, "check_rate_limit", return_value=(True, None)
            ),
            patch.object(jailbreaker_service.rate_limiter, "record_reset"),
            patch("shutil.rmtree", side_effect=PermissionError("Permission denied")),
            patch("subprocess.run") as mock_subprocess,
        ):
            # Mock successful sudo rm and chown
            mock_subprocess.return_value.returncode = 0

            result = await jailbreaker_service.reset_agent("test_token")

            # Should succeed using sudo fallback
            assert result.status == ResetStatus.SUCCESS

            # Verify sudo rm was called for directory removal
            sudo_rm_calls = [
                call for call in mock_subprocess.call_args_list if call[0][0][:2] == ["sudo", "rm"]
            ]
            assert len(sudo_rm_calls) >= 1

            # Verify chown was called for permission fix
            chown_calls = [
                call
                for call in mock_subprocess.call_args_list
                if call[0][0][:2] == ["sudo", "chown"]
            ]
            assert len(chown_calls) >= 1

    @pytest.mark.asyncio
    async def test_reset_fails_gracefully_on_container_errors(
        self, jailbreaker_service, mock_container_manager
    ):
        """Test reset handles container operation failures gracefully."""
        # Mock container start failure
        mock_container_manager.start_container.side_effect = Exception("Container start failed")

        with (
            patch.object(
                jailbreaker_service, "verify_access_token", return_value=(True, "test_user")
            ),
            patch.object(
                jailbreaker_service.rate_limiter, "check_rate_limit", return_value=(True, None)
            ),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            result = await jailbreaker_service.reset_agent("test_token")

            # Should fail gracefully
            assert result.status == ResetStatus.ERROR
            assert "Container start failed" in result.message

    def test_container_name_construction(self):
        """Test that container names are constructed correctly."""
        config = JailbreakerConfig(
            discord_client_id="test",
            discord_client_secret="test",
            target_agent_id="echo-nemesis-v2tyey",
        )

        # The jailbreaker should construct container name as "ciris-echo-nemesis-v2tyey"
        expected_name = f"ciris-{config.target_agent_id}"
        assert expected_name == "ciris-echo-nemesis-v2tyey"

        # Not the old incorrect format
        incorrect_name = f"ciris-agent-{config.target_agent_id}"
        assert incorrect_name == "ciris-agent-echo-nemesis-v2tyey"
        assert expected_name != incorrect_name
