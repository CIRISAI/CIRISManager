"""
Test shutdown message formatting in deployment orchestrator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from ciris_manager.deployment_orchestrator import DeploymentOrchestrator
from ciris_manager.models import UpdateNotification, AgentInfo


class TestShutdownMessage:
    """Test shutdown message formatting."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance."""
        manager = Mock()
        manager.agent_registry = Mock()
        manager.agent_registry.get_agent = Mock(return_value=None)
        return DeploymentOrchestrator(manager)

    @pytest.mark.asyncio
    async def test_shutdown_message_with_commit_sha(self, orchestrator):
        """Test shutdown message when version is a commit SHA."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="78500ea1234567890abcdef",
            message="Update available",
            strategy="canary"
        )
        
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general"
        )
        
        deployment_id = "23a69b03-f44a-4026-8ce9-910b57bdb759"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json = Mock(return_value={"status": "shutting_down"})
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            result = await orchestrator._update_single_agent(
                deployment_id, notification, agent
            )
            
            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs['json']
            
            # Should format commit SHA nicely
            expected_reason = "System shutdown requested: Runtime: CD update to commit 78500ea (deployment 23a69b03) (API shutdown by wa-system-admin)"
            assert shutdown_payload['reason'] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_with_semantic_version(self, orchestrator):
        """Test shutdown message with semantic version."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="v2.1.0",
            message="Security update",
            strategy="immediate"
        )
        
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general"
        )
        
        deployment_id = "abc-123-def"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json = Mock(return_value={"status": "shutting_down"})
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            result = await orchestrator._update_single_agent(
                deployment_id, notification, agent
            )
            
            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs['json']
            
            # Should format semantic version nicely
            expected_reason = "System shutdown requested: Runtime: CD update to version v2.1.0 - Security update (deployment abc-123-) (API shutdown by wa-system-admin)"
            assert shutdown_payload['reason'] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_without_version(self, orchestrator):
        """Test shutdown message when no version provided."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            message="Emergency fix",
            strategy="immediate"
        )
        
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general"
        )
        
        deployment_id = "xyz-789"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json = Mock(return_value={"status": "shutting_down"})
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            result = await orchestrator._update_single_agent(
                deployment_id, notification, agent
            )
            
            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs['json']
            
            # Should handle missing version gracefully
            expected_reason = "System shutdown requested: Runtime: CD update requested - Emergency fix (deployment xyz-789) (API shutdown by wa-system-admin)"
            assert shutdown_payload['reason'] == expected_reason

    @pytest.mark.asyncio
    async def test_shutdown_message_numeric_version(self, orchestrator):
        """Test shutdown message with numeric version (no v prefix)."""
        notification = UpdateNotification(
            agent_image="ghcr.io/cirisai/ciris-agent:latest",
            version="2.1.0",
            message="Update available",
            strategy="canary"
        )
        
        agent = AgentInfo(
            agent_id="test-agent",
            agent_name="Test Agent",
            api_port=8080,
            container_name="ciris-test-agent",
            deployment_group="general"
        )
        
        deployment_id = "test-deployment-456"
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json = Mock(return_value={"status": "shutting_down"})
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            result = await orchestrator._update_single_agent(
                deployment_id, notification, agent
            )
            
            # Check the shutdown payload
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            shutdown_payload = call_args.kwargs['json']
            
            # Should recognize numeric version as semantic version
            expected_reason = "System shutdown requested: Runtime: CD update to version 2.1.0 (deployment test-dep) (API shutdown by wa-system-admin)"
            assert shutdown_payload['reason'] == expected_reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])