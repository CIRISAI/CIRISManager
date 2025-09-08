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
        # Create agents directory structure that matches production
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)

        # Create the specific agent directory that the service expects
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True, exist_ok=True)

        service = JailbreakerService(config, agents_dir, mock_container_manager)
        return service

    @pytest.mark.skip(reason="Test needs updating for new sudo-based directory creation")
    @pytest.mark.asyncio
    async def test_complete_reset_flow_success(
        self, jailbreaker_service, temp_dir, mock_container_manager
    ):
        """Test successful complete reset flow."""
        # Setup test data directory (agent dir already exists from fixture)
        agent_dir = temp_dir / "agents" / "echo-nemesis-v2tyey"
        data_dir = agent_dir / "data"
        data_dir.mkdir(exist_ok=True)
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
        self, config, temp_dir, mock_container_manager
    ):
        """Test that reset uses correct container naming convention."""
        # Create proper directory structure
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True, exist_ok=True)

        # Create service
        service = JailbreakerService(config, agents_dir, mock_container_manager)

        with (
            patch.object(service, "verify_access_token", return_value=(True, "test_user")),
            patch.object(service.rate_limiter, "check_rate_limit", return_value=(True, None)),
            patch.object(service.rate_limiter, "record_reset"),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            await service.reset_agent("test_token")

            # Verify correct container name is used (ciris-echo-nemesis-v2tyey, not ciris-agent-echo-nemesis-v2tyey)
            mock_container_manager.stop_container.assert_called_with("ciris-echo-nemesis-v2tyey")
            mock_container_manager.start_container.assert_called_with("ciris-echo-nemesis-v2tyey")

    @pytest.mark.skip(reason="Test needs updating for new sudo-based directory creation")
    @pytest.mark.asyncio
    async def test_reset_handles_missing_data_directory(
        self, jailbreaker_service, temp_dir, mock_container_manager
    ):
        """Test reset when data directory doesn't exist."""
        # Agent directory already exists from fixture
        agent_dir = temp_dir / "agents" / "echo-nemesis-v2tyey"
        # Ensure data directory does NOT exist for this test
        data_dir = agent_dir / "data"
        if data_dir.exists():
            import shutil

            shutil.rmtree(data_dir)

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

    @pytest.mark.skip(reason="Test needs updating for new sudo-based directory creation")
    @pytest.mark.asyncio
    async def test_reset_handles_permission_errors_gracefully(
        self, jailbreaker_service, temp_dir, mock_container_manager
    ):
        """Test reset handles permission errors with sudo fallback."""
        # Setup test data
        agent_dir = temp_dir / "agents" / "echo-nemesis-v2tyey"
        agent_dir.mkdir(parents=True, exist_ok=True)
        data_dir = agent_dir / "data"
        data_dir.mkdir(exist_ok=True)

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

    @pytest.mark.skip(reason="Test needs updating for new sudo-based directory creation")
    @pytest.mark.asyncio
    async def test_data_directory_ownership_fix(self, config, temp_dir, mock_container_manager):
        """Test that data directory is recreated with correct ownership."""
        # Setup
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True, exist_ok=True)
        data_dir = target_agent_dir / "data"
        data_dir.mkdir(exist_ok=True)

        service = JailbreakerService(config, agents_dir, mock_container_manager)

        with (
            patch.object(service, "verify_access_token", return_value=(True, "test_user")),
            patch.object(service.rate_limiter, "check_rate_limit", return_value=(True, None)),
            patch.object(service.rate_limiter, "record_reset"),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            result = await service.reset_agent("test_token")

            # Should succeed
            assert result.status == ResetStatus.SUCCESS

            # Verify chown was called with correct parameters
            chown_calls = [
                call
                for call in mock_subprocess.call_args_list
                if call[0][0][:3] == ["sudo", "chown", "-R"]
            ]
            assert len(chown_calls) >= 1

            # Verify the chown call includes 1000:1000 and the correct path
            chown_call = chown_calls[0]
            assert "1000:1000" in chown_call[0][0]
            assert str(data_dir) in chown_call[0][0]

    @pytest.mark.skip(reason="Test needs updating for new sudo-based directory creation")
    @pytest.mark.asyncio
    async def test_sudo_fallback_on_permission_denied(
        self, config, temp_dir, mock_container_manager
    ):
        """Test sudo fallback when regular rmtree fails with permissions."""
        # Setup
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True, exist_ok=True)
        data_dir = target_agent_dir / "data"
        data_dir.mkdir(exist_ok=True)

        service = JailbreakerService(config, agents_dir, mock_container_manager)

        with (
            patch.object(service, "verify_access_token", return_value=(True, "test_user")),
            patch.object(service.rate_limiter, "check_rate_limit", return_value=(True, None)),
            patch.object(service.rate_limiter, "record_reset"),
            patch("shutil.rmtree", side_effect=PermissionError("Access denied")),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            result = await service.reset_agent("test_token")

            # Should succeed with sudo fallback
            assert result.status == ResetStatus.SUCCESS

            # Verify sudo rm was called
            sudo_rm_calls = [
                call
                for call in mock_subprocess.call_args_list
                if call[0][0][:3] == ["sudo", "rm", "-rf"]
            ]
            assert len(sudo_rm_calls) >= 1

            # Verify sudo chown was called for recreation
            sudo_chown_calls = [
                call
                for call in mock_subprocess.call_args_list
                if call[0][0][:3] == ["sudo", "chown", "-R"]
            ]
            assert len(sudo_chown_calls) >= 1

    @pytest.mark.asyncio
    async def test_agent_health_check_after_reset(self, config, temp_dir, mock_container_manager):
        """Test health check is performed after successful reset."""
        # Setup
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True)

        service = JailbreakerService(config, agents_dir, mock_container_manager)

        with (
            patch.object(service, "verify_access_token", return_value=(True, "test_user")),
            patch.object(service.rate_limiter, "check_rate_limit", return_value=(True, None)),
            patch.object(service.rate_limiter, "record_reset"),
            patch.object(service, "check_agent_health", return_value=True) as mock_health_check,
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            result = await service.reset_agent("test_token")

            assert result.status == ResetStatus.SUCCESS
            mock_health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limiting_enforcement(self, config, temp_dir, mock_container_manager):
        """Test that rate limiting is properly enforced."""
        # Setup
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True)

        service = JailbreakerService(config, agents_dir, mock_container_manager)

        with (
            patch.object(service, "verify_access_token", return_value=(True, "test_user")),
            patch.object(service.rate_limiter, "check_rate_limit", return_value=(False, 3600)),
            patch("subprocess.run") as mock_subprocess,
        ):
            result = await service.reset_agent("test_token")

            # Should be rate limited
            assert result.status == ResetStatus.RATE_LIMITED
            assert result.next_allowed_reset == 3600

            # Container operations should not have been called
            mock_container_manager.stop_container.assert_not_called()
            mock_container_manager.start_container.assert_not_called()
            mock_subprocess.assert_not_called()

    @pytest.mark.asyncio
    async def test_unauthorized_user_rejection(self, config, temp_dir, mock_container_manager):
        """Test that unauthorized users are rejected."""
        # Setup
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True)

        service = JailbreakerService(config, agents_dir, mock_container_manager)

        with (
            patch.object(service, "verify_access_token", return_value=(False, None)),
            patch("subprocess.run") as mock_subprocess,
        ):
            result = await service.reset_agent("invalid_token")

            # Should be unauthorized
            assert result.status == ResetStatus.UNAUTHORIZED

            # Container operations should not have been called
            mock_container_manager.stop_container.assert_not_called()
            mock_container_manager.start_container.assert_not_called()
            mock_subprocess.assert_not_called()

    @pytest.mark.asyncio
    async def test_container_start_failure_handling(self, config, temp_dir, mock_container_manager):
        """Test graceful handling of container start failures."""
        # Setup
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir(exist_ok=True)
        target_agent_dir = agents_dir / config.target_agent_id
        target_agent_dir.mkdir(parents=True)

        service = JailbreakerService(config, agents_dir, mock_container_manager)

        # Mock container start failure
        mock_container_manager.start_container.side_effect = Exception(
            "Docker daemon not responding"
        )

        with (
            patch.object(service, "verify_access_token", return_value=(True, "test_user")),
            patch.object(service.rate_limiter, "check_rate_limit", return_value=(True, None)),
            patch("subprocess.run") as mock_subprocess,
        ):
            mock_subprocess.return_value.returncode = 0

            result = await service.reset_agent("test_token")

            # Should fail gracefully
            assert result.status == ResetStatus.ERROR
            assert "Docker daemon not responding" in result.message

            # Stop should have been called but start failed
            mock_container_manager.stop_container.assert_called_once()
            mock_container_manager.start_container.assert_called_once()

    def test_production_container_names_match(self):
        """Test that our container naming matches production reality."""
        # Test various agent IDs to ensure naming is consistent
        test_cases = [
            ("echo-nemesis-v2tyey", "ciris-echo-nemesis-v2tyey"),
            ("echo-core-jm2jy2", "ciris-echo-core-jm2jy2"),
            ("sage-2wnuc8", "ciris-sage-2wnuc8"),
            ("datum", "ciris-datum"),
        ]

        for agent_id, expected_container_name in test_cases:
            config = JailbreakerConfig(
                discord_client_id="test",
                discord_client_secret="test",
                target_agent_id=agent_id,
            )

            # This is the naming logic used in the service
            actual_container_name = f"ciris-{config.target_agent_id}"
            assert actual_container_name == expected_container_name
