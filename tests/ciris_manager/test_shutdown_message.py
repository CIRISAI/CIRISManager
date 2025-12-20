"""
Test shutdown message formatting in deployment orchestrator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from ciris_manager.deployment import DeploymentOrchestrator
from ciris_manager.models import UpdateNotification, AgentInfo


class TestShutdownMessage:
    """Test shutdown message formatting."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance."""
        manager = Mock()
        manager.agent_registry = Mock()
        # Return agent info with service token
        agent_info = Mock()
        agent_info.service_token = "test-service-token"
        manager.agent_registry.get_agent = Mock(return_value=agent_info)
        return DeploymentOrchestrator(manager)

    @pytest.mark.asyncio
    async def test_shutdown_message_with_commit_sha(self, orchestrator):
        """Test shutdown message when version is a commit SHA."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="78500ea1234567890abcdef",
            message="Update available",
            strategy="canary",
        )

        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general",
        )

        deployment_id = "23a69b03-f44a-4026-8ce9-910b57bdb759"

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json = Mock(return_value={"status": "shutting_down"})

                mock_post = AsyncMock(return_value=mock_response)
                mock_client.return_value.__aenter__.return_value.post = mock_post

                await orchestrator._update_single_agent(deployment_id, notification, agent)

            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs["json"]

            # Should format commit SHA nicely
            expected_reason = "Select TASK_COMPLETE to accept this verified automatic update: Runtime: CD update to commit 78500ea (deployment 23a69b03) (API shutdown by wa-system-admin)"
            assert shutdown_payload["reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_with_semantic_version(self, orchestrator):
        """Test shutdown message with semantic version."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="v2.1.0",
            message="Security update",
            strategy="immediate",
        )

        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general",
        )

        deployment_id = "abc-123-def"

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json = Mock(return_value={"status": "shutting_down"})

                mock_post = AsyncMock(return_value=mock_response)
                mock_client.return_value.__aenter__.return_value.post = mock_post

                await orchestrator._update_single_agent(deployment_id, notification, agent)

            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs["json"]

            # Should format semantic version nicely
            expected_reason = "Select TASK_COMPLETE to accept this verified automatic update: Runtime: CD update to version v2.1.0 (deployment abc-123-) - Security update (API shutdown by wa-system-admin)"
            assert shutdown_payload["reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_without_version(self, orchestrator):
        """Test shutdown message when no version provided."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            message="Emergency fix",
            strategy="immediate",
        )

        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general",
        )

        deployment_id = "xyz-789"

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json = Mock(return_value={"status": "shutting_down"})

                mock_post = AsyncMock(return_value=mock_response)
                mock_client.return_value.__aenter__.return_value.post = mock_post

                await orchestrator._update_single_agent(deployment_id, notification, agent)

            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs["json"]

            # Should handle missing version gracefully
            expected_reason = "Select TASK_COMPLETE to accept this verified automatic update: Runtime: CD update requested (deployment xyz-789) - Emergency fix (API shutdown by wa-system-admin)"
            assert shutdown_payload["reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_numeric_version(self, orchestrator):
        """Test shutdown message with numeric version (no v prefix)."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="2.1.0",
            message="Update available",
            strategy="canary",
        )

        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general",
        )

        deployment_id = "test-deployment-456"

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json = Mock(return_value={"status": "shutting_down"})

                mock_post = AsyncMock(return_value=mock_response)
                mock_client.return_value.__aenter__.return_value.post = mock_post

                await orchestrator._update_single_agent(deployment_id, notification, agent)

            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs["json"]

            # Should recognize numeric version as semantic version and add v prefix
            expected_reason = "Select TASK_COMPLETE to accept this verified automatic update: Runtime: CD update to version v2.1.0 (deployment test-dep) (API shutdown by wa-system-admin)"
            assert shutdown_payload["reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_with_full_changelog(self, orchestrator):
        """Test shutdown message with full changelog (multiple commit messages)."""
        changelog = """fix: improve shutdown reason message formatting
feat: add template parameter to agent containers
fix: env file parsing improvements
test: add comprehensive file loading tests
chore: bump version to 2.1.1"""

        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="v2.1.1",
            changelog=changelog,
            strategy="canary",
        )

        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general",
        )

        deployment_id = "release-deployment-789"

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json = Mock(return_value={"status": "shutting_down"})

                mock_post = AsyncMock(return_value=mock_response)
                mock_client.return_value.__aenter__.return_value.post = mock_post

                await orchestrator._update_single_agent(deployment_id, notification, agent)

            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs["json"]

            # Should include formatted changelog
            expected_reason = """Select TASK_COMPLETE to accept this verified automatic update: Runtime: CD update to version v2.1.1 (deployment release-)
Release notes:
  • fix: improve shutdown reason message formatting
  • feat: add template parameter to agent containers
  • fix: env file parsing improvements
  • test: add comprehensive file loading tests
  • chore: bump version to 2.1.1 (API shutdown by wa-system-admin)"""
            assert shutdown_payload["reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_with_single_line_changelog(self, orchestrator):
        """Test shutdown message with single line changelog."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="v2.1.2",
            changelog="fix: critical security patch",
            strategy="immediate",
        )

        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general",
        )

        deployment_id = "hotfix-123"

        # Mock agent_auth to bypass encryption
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer service:test-token"}
        with patch("ciris_manager.agent_auth.get_agent_auth", return_value=mock_auth):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json = Mock(return_value={"status": "shutting_down"})

                mock_post = AsyncMock(return_value=mock_response)
                mock_client.return_value.__aenter__.return_value.post = mock_post

                await orchestrator._update_single_agent(deployment_id, notification, agent)

            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs["json"]

            # Should include single line changelog inline
            expected_reason = "Select TASK_COMPLETE to accept this verified automatic update: Runtime: CD update to version v2.1.2 (deployment hotfix-1) - fix: critical security patch (API shutdown by wa-system-admin)"
            assert shutdown_payload["reason"] == expected_reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
