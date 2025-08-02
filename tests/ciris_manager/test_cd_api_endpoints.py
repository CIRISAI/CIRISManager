"""
Tests for CD orchestration API endpoints.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone
import os

from ciris_manager.models import (
    UpdateNotification,
    DeploymentStatus,
    AgentInfo,
)


class TestCDAPIEndpoints:
    """Test CD orchestration API endpoints."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock manager."""
        manager = Mock()
        manager.agent_registry = Mock()
        manager.agent_registry.list_agents = Mock(return_value=[
            AgentInfo(
                agent_id="agent-1",
                agent_name="Agent 1",
                container_name="ciris-agent-1",
                api_port=8080,
                status="running",
            ),
            AgentInfo(
                agent_id="agent-2",
                agent_name="Agent 2",
                container_name="ciris-agent-2",
                api_port=8081,
                status="running",
            ),
        ])
        return manager

    @pytest.fixture
    def mock_orchestrator(self):
        """Create mock orchestrator."""
        orchestrator = MagicMock()
        return orchestrator

    @pytest.fixture
    def app_with_mocked_orchestrator(self, mock_manager, mock_orchestrator):
        """Create app with mocked orchestrator."""
        # Set dev mode for mock auth
        os.environ["CIRIS_AUTH_MODE"] = "development"
        # Set test deployment token
        os.environ["CIRIS_DEPLOY_TOKEN"] = "test-deploy-token"
        
        # Patch the DeploymentOrchestrator before importing routes
        with patch("ciris_manager.api.routes.DeploymentOrchestrator") as mock_orch_class:
            mock_orch_class.return_value = mock_orchestrator
            
            # Now import and create routes
            from ciris_manager.api.routes import create_routes
            
            app = FastAPI()
            router = create_routes(mock_manager)
            app.include_router(router, prefix="/manager/v1")
            
            yield app, mock_orchestrator

    def test_notify_update_success(self, app_with_mocked_orchestrator):
        """Test successful update notification."""
        app, mock_orchestrator = app_with_mocked_orchestrator
        client = TestClient(app)
        
        notification = {
            "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0",
            "gui_image": "ghcr.io/cirisai/ciris-gui:v2.0",
            "message": "Security update available",
            "strategy": "canary",
            "metadata": {"version": "2.0"},
        }

        mock_status = DeploymentStatus(
            deployment_id="test-deployment-123",
            agents_total=2,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Security update available",
            canary_phase="explorers",
        )
        mock_orchestrator.start_deployment = AsyncMock(return_value=mock_status)

        # Include deployment token authentication
        headers = {"Authorization": "Bearer test-deploy-token"}
        response = client.post("/manager/v1/updates/notify", json=notification, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["deployment_id"] == "test-deployment-123"
        assert data["agents_total"] == 2
        assert data["status"] == "in_progress"
        assert data["canary_phase"] == "explorers"

    def test_notify_update_deployment_in_progress(self, app_with_mocked_orchestrator):
        """Test notification rejected when deployment in progress."""
        app, mock_orchestrator = app_with_mocked_orchestrator
        client = TestClient(app)
        
        notification = {
            "agent_image": "ghcr.io/cirisai/ciris-agent:v2.0",
            "message": "Another update",
            "strategy": "canary",
        }

        mock_orchestrator.start_deployment = AsyncMock(
            side_effect=ValueError("Deployment already in progress")
        )

        headers = {"Authorization": "Bearer test-deploy-token"}
        response = client.post("/manager/v1/updates/notify", json=notification, headers=headers)

        assert response.status_code == 409
        assert "Deployment already in progress" in response.json()["detail"]

    def test_get_deployment_status_by_id(self, app_with_mocked_orchestrator):
        """Test getting deployment status by ID."""
        app, mock_orchestrator = app_with_mocked_orchestrator
        client = TestClient(app)
        
        mock_status = DeploymentStatus(
            deployment_id="test-deployment-123",
            agents_total=10,
            agents_updated=5,
            agents_deferred=2,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Updating agents",
            canary_phase="early_adopters",
        )
        mock_orchestrator.get_deployment_status = AsyncMock(return_value=mock_status)

        headers = {"Authorization": "Bearer test-deploy-token"}
        response = client.get(
            "/manager/v1/updates/status",
            params={"deployment_id": "test-deployment-123"},
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deployment_id"] == "test-deployment-123"
        assert data["agents_updated"] == 5
        assert data["agents_deferred"] == 2
        assert data["canary_phase"] == "early_adopters"

    def test_get_current_deployment(self, app_with_mocked_orchestrator):
        """Test getting current active deployment."""
        app, mock_orchestrator = app_with_mocked_orchestrator
        client = TestClient(app)
        
        mock_status = DeploymentStatus(
            deployment_id="current-deployment",
            agents_total=20,
            agents_updated=20,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            status="completed",
            message="All agents updated",
        )
        mock_orchestrator.get_current_deployment = AsyncMock(return_value=mock_status)
        mock_orchestrator.get_deployment_status = AsyncMock(return_value=None)

        headers = {"Authorization": "Bearer test-deploy-token"}
        response = client.get("/manager/v1/updates/status", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["deployment_id"] == "current-deployment"
        assert data["status"] == "completed"
        assert data["agents_updated"] == 20

    def test_get_deployment_status_not_found(self, app_with_mocked_orchestrator):
        """Test getting status for non-existent deployment."""
        app, mock_orchestrator = app_with_mocked_orchestrator
        client = TestClient(app)
        
        mock_orchestrator.get_deployment_status = AsyncMock(return_value=None)
        mock_orchestrator.get_current_deployment = AsyncMock(return_value=None)

        headers = {"Authorization": "Bearer test-deploy-token"}
        response = client.get(
            "/manager/v1/updates/status",
            params={"deployment_id": "non-existent"},
            headers=headers
        )

        assert response.status_code == 200
        assert response.json() is None

    def test_immediate_deployment_strategy(self, app_with_mocked_orchestrator):
        """Test immediate deployment strategy."""
        app, mock_orchestrator = app_with_mocked_orchestrator
        client = TestClient(app)
        
        notification = {
            "agent_image": "ghcr.io/cirisai/ciris-agent:emergency",
            "message": "Emergency security patch",
            "strategy": "immediate",
        }

        mock_status = DeploymentStatus(
            deployment_id="emergency-deployment",
            agents_total=5,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="in_progress",
            message="Emergency security patch",
            canary_phase=None,  # No phases for immediate
        )
        mock_orchestrator.start_deployment = AsyncMock(return_value=mock_status)

        headers = {"Authorization": "Bearer test-deploy-token"}
        response = client.post("/manager/v1/updates/notify", json=notification, headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["deployment_id"] == "emergency-deployment"
        assert data["canary_phase"] is None  # No canary for immediate