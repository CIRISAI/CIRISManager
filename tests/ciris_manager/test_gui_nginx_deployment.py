"""
Tests for GUI and nginx container deployment and rollback functionality.
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import UpdateNotification


class TestGuiNginxDeployment:
    """Test GUI and nginx container deployment and rollback."""

    @pytest.fixture
    def orchestrator(self):
        """Create a deployment orchestrator instance."""
        mock_manager = Mock()
        mock_manager.agent_registry = Mock()
        mock_manager.update_nginx_config = AsyncMock(return_value=True)

        orchestrator = DeploymentOrchestrator(manager=mock_manager)
        orchestrator.registry_client = Mock()
        orchestrator.registry_client.resolve_image_digest = AsyncMock(return_value="sha256:test123")

        return orchestrator

    @pytest.mark.asyncio
    async def test_gui_only_update(self, orchestrator):
        """Test updating only the GUI container."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.0.0",
            gui_image="ghcr.io/cirisai/ciris-gui:v2.0.0",
            message="GUI update only",
        )

        # Mock subprocess calls
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            # Mock file operations
            with patch("pathlib.Path.exists", return_value=False):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", MagicMock()):
                        result = await orchestrator._update_nginx_container(
                            gui_image=notification.gui_image, nginx_image=None
                        )

        assert result is True
        # Verify docker pull was called for GUI image
        mock_subprocess.assert_any_call(
            "docker", "pull", "ghcr.io/cirisai/ciris-gui:v2.0.0", stdout=-1, stderr=-1
        )

    @pytest.mark.asyncio
    async def test_nginx_and_gui_update(self, orchestrator):
        """Test updating both nginx and GUI containers."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:v1.0.0",
            gui_image="ghcr.io/cirisai/ciris-gui:v2.0.0",
            nginx_image="nginx:1.25.0",
            message="Full infrastructure update",
        )

        # Mock subprocess calls
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            # Mock file operations
            with patch("pathlib.Path.exists", return_value=False):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", MagicMock()):
                        result = await orchestrator._update_nginx_container(
                            gui_image=notification.gui_image, nginx_image=notification.nginx_image
                        )

        assert result is True
        # Verify docker pull was called for both images
        mock_subprocess.assert_any_call(
            "docker", "pull", "ghcr.io/cirisai/ciris-gui:v2.0.0", stdout=-1, stderr=-1
        )
        mock_subprocess.assert_any_call("docker", "pull", "nginx:1.25.0", stdout=-1, stderr=-1)

    @pytest.mark.asyncio
    async def test_version_storage(self, orchestrator, tmp_path):
        """Test that version history is properly stored."""
        # Use temp directory for testing
        version_file = tmp_path / "gui_versions.json"

        # Mock the Path constructor to return our temp file
        original_path = Path

        def mock_path_constructor(path_str):
            if "gui_versions.json" in str(path_str):
                return version_file
            return original_path(path_str)

        with patch("ciris_manager.deployment_orchestrator.Path", side_effect=mock_path_constructor):
            # First deployment
            await orchestrator._store_container_version("gui", "gui:v1.0.0")

            # Check file was created
            assert version_file.exists()
            with open(version_file) as f:
                versions = json.load(f)
            assert versions["current"] == "gui:v1.0.0"
            assert "n-1" not in versions

            # Second deployment
            await orchestrator._store_container_version("gui", "gui:v2.0.0")

            # Check rotation happened
            with open(version_file) as f:
                versions = json.load(f)
            assert versions["current"] == "gui:v2.0.0"
            assert versions["n-1"] == "gui:v1.0.0"
            assert "n-2" not in versions

            # Third deployment
            await orchestrator._store_container_version("gui", "gui:v3.0.0")

            # Check full rotation
            with open(version_file) as f:
                versions = json.load(f)
            assert versions["current"] == "gui:v3.0.0"
            assert versions["n-1"] == "gui:v2.0.0"
            assert versions["n-2"] == "gui:v1.0.0"

    @pytest.mark.asyncio
    async def test_gui_rollback(self, orchestrator, tmp_path):
        """Test rolling back GUI container to previous version."""
        # Setup version history
        version_file = tmp_path / "gui_versions.json"
        versions = {"current": "gui:v3.0.0", "n-1": "gui:v2.0.0", "n-2": "gui:v1.0.0"}
        version_file.parent.mkdir(parents=True, exist_ok=True)
        with open(version_file, "w") as f:
            json.dump(versions, f)

        # Mock subprocess calls
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            # Mock Path to use our temp file
            original_path = Path

            def mock_path_constructor(path_str):
                if "gui_versions.json" in str(path_str):
                    return version_file
                return original_path(path_str)

            with patch(
                "ciris_manager.deployment_orchestrator.Path", side_effect=mock_path_constructor
            ):
                result = await orchestrator._rollback_gui_container("n-1")

        assert result is True
        # Verify docker-compose was called with the rollback image
        mock_subprocess.assert_called_with(
            "docker-compose",
            "-f",
            "/opt/ciris/docker-compose.yml",
            "up",
            "-d",
            "--no-deps",
            "gui",
            stdout=-1,
            stderr=-1,
            env={
                "CIRIS_GUI_IMAGE": "gui:v2.0.0",
                **orchestrator._rollback_gui_container.__globals__.get("os", Mock()).environ,
            },
        )

    @pytest.mark.asyncio
    async def test_nginx_rollback(self, orchestrator, tmp_path):
        """Test rolling back nginx container to previous version."""
        # Setup version history
        version_file = tmp_path / "nginx_versions.json"
        versions = {"current": "nginx:1.25.0", "n-1": "nginx:1.24.0", "n-2": "nginx:1.23.0"}
        version_file.parent.mkdir(parents=True, exist_ok=True)
        with open(version_file, "w") as f:
            json.dump(versions, f)

        # Mock subprocess calls
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.returncode = 0
            mock_subprocess.return_value = mock_process

            # Mock Path to use our temp file
            original_path = Path

            def mock_path_constructor(path_str):
                if "nginx_versions.json" in str(path_str):
                    return version_file
                return original_path(path_str)

            with patch(
                "ciris_manager.deployment_orchestrator.Path", side_effect=mock_path_constructor
            ):
                result = await orchestrator._rollback_nginx_container("n-1")

        assert result is True
        # Verify docker-compose was called with the rollback image
        mock_subprocess.assert_called_with(
            "docker-compose",
            "-f",
            "/opt/ciris/docker-compose.yml",
            "up",
            "-d",
            "--no-deps",
            "nginx",
            stdout=-1,
            stderr=-1,
            env={
                "NGINX_IMAGE": "nginx:1.24.0",
                **orchestrator._rollback_nginx_container.__globals__.get("os", Mock()).environ,
            },
        )

    @pytest.mark.asyncio
    async def test_rollback_proposal_with_gui_nginx(self, orchestrator, tmp_path):
        """Test creating a rollback proposal that includes GUI and nginx."""
        # Setup version files
        gui_file = tmp_path / "gui_versions.json"
        nginx_file = tmp_path / "nginx_versions.json"

        gui_versions = {"current": "gui:v2.0.0", "n-1": "gui:v1.0.0"}
        nginx_versions = {"current": "nginx:1.25.0", "n-1": "nginx:1.24.0"}

        gui_file.parent.mkdir(parents=True, exist_ok=True)
        with open(gui_file, "w") as f:
            json.dump(gui_versions, f)
        with open(nginx_file, "w") as f:
            json.dump(nginx_versions, f)

        # Create a deployment
        deployment_id = "test-deploy-123"
        orchestrator.deployments[deployment_id] = Mock(status="in_progress")

        # Mock agent list
        agents = [
            Mock(agent_id="agent-1", agent_name="Agent 1"),
            Mock(agent_id="agent-2", agent_name="Agent 2"),
        ]

        # Mock file paths
        with patch("pathlib.Path") as mock_path:

            def path_side_effect(path_str):
                if "gui_versions" in path_str:
                    return gui_file
                elif "nginx_versions" in path_str:
                    return nginx_file
                else:
                    mock = Mock()
                    mock.exists.return_value = False
                    return mock

            mock_path.side_effect = path_side_effect

            # Mock audit
            with patch("ciris_manager.audit.audit_deployment_action"):
                await orchestrator._propose_rollback(
                    deployment_id=deployment_id,
                    reason="Test rollback",
                    affected_agents=agents,
                    include_gui=True,
                    include_nginx=True,
                )

        # Check rollback proposal was created
        assert hasattr(orchestrator, "rollback_proposals")
        assert deployment_id in orchestrator.rollback_proposals

        proposal = orchestrator.rollback_proposals[deployment_id]
        assert proposal["reason"] == "Test rollback"
        assert "rollback_targets" in proposal

        targets = proposal["rollback_targets"]
        assert "agents" in targets
        assert len(targets["agents"]) == 2
        assert "gui" in targets
        assert targets["gui"] == "n-1"
        assert "nginx" in targets
        assert targets["nginx"] == "n-1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
