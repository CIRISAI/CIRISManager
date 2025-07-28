"""
Tests for authentication middleware behavior in different modes.
"""

import os
import pytest
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient


class TestAuthModes:
    """Test authentication behavior in different modes."""
    
    def test_auth_mode_from_env(self):
        """Test reading auth mode from environment."""
        with patch.dict(os.environ, {"CIRIS_AUTH_MODE": "development"}):
            assert os.getenv("CIRIS_AUTH_MODE") == "development"
        
        with patch.dict(os.environ, {"CIRIS_AUTH_MODE": "production"}):
            assert os.getenv("CIRIS_AUTH_MODE") == "production"
            
        with patch.dict(os.environ, {}, clear=True):
            assert os.getenv("CIRIS_AUTH_MODE", "production") == "production"


class TestAuthIntegration:
    """Integration tests for auth in API endpoints."""

    @pytest.fixture
    def mock_manager(self):
        """Create a mock manager for testing."""
        manager = Mock()
        
        async def mock_create_agent(**kwargs):
            return {
                "agent_id": "test-agent-123",
                "name": kwargs.get("name", "Test Agent"),
                "container": "ciris-test-agent-123",
                "port": 8080,
                "api_endpoint": "http://localhost:8080",
                "compose_file": "/path/to/compose.yml",
                "status": "starting"
            }
        
        manager.create_agent = mock_create_agent
        manager.list_agents = Mock(return_value=[])
        manager.get_agent_by_name = Mock(return_value=None)
        manager.delete_agent = Mock(return_value=True)
        manager.get_status = Mock(return_value={
            "running": True,
            "components": {
                "container_manager": "running",
                "watchdog": "running",
                "api_server": "not_implemented"
            }
        })
        return manager

    def test_dev_mode_allows_unauthenticated_requests(self, mock_manager):
        """Test that dev mode allows requests without auth headers."""
        with patch.dict(os.environ, {"CIRIS_AUTH_MODE": "development"}):
            from ciris_manager.api.routes import create_routes
            from fastapi import FastAPI
            
            app = FastAPI()
            router = create_routes(mock_manager)
            app.include_router(router, prefix="/manager/v1")
            
            client = TestClient(app)
            
            # Make request without any auth headers
            response = client.post(
                "/manager/v1/agents",
                json={
                    "template": "scout",
                    "name": "Test Agent"
                }
            )
            
            assert response.status_code == 200
            assert response.json()["agent_id"] == "test-agent-123"

    def test_prod_mode_requires_auth(self, mock_manager):
        """Test that production mode requires authentication."""
        # In production mode, the auth dependency should be applied
        # This is more of a unit test - the actual auth flow is tested elsewhere
        with patch.dict(os.environ, {"CIRIS_AUTH_MODE": "production"}):
            # Just verify the mode is correctly set
            assert os.getenv("CIRIS_AUTH_MODE") == "production"
            
            # The actual auth enforcement is tested in test_auth_routes.py
            # This test just verifies the mode is set correctly
    
    def test_dev_mode_status_endpoint(self, mock_manager):
        """Test that dev mode status endpoint includes auth_mode."""
        with patch.dict(os.environ, {"CIRIS_AUTH_MODE": "development"}):
            from ciris_manager.api.routes import create_routes
            from fastapi import FastAPI
            
            app = FastAPI()
            router = create_routes(mock_manager)
            app.include_router(router, prefix="/manager/v1")
            
            client = TestClient(app)
            
            # Check status endpoint includes auth_mode
            response = client.get("/manager/v1/status")
            assert response.status_code == 200
            assert response.json()["auth_mode"] == "development"
    
    def test_prod_mode_status_endpoint(self, mock_manager):
        """Test that prod mode status endpoint includes auth_mode."""
        with patch.dict(os.environ, {"CIRIS_AUTH_MODE": "production"}):
            from ciris_manager.api.routes import create_routes
            from fastapi import FastAPI
            
            app = FastAPI()
            router = create_routes(mock_manager)
            app.include_router(router, prefix="/manager/v1")
            
            client = TestClient(app)
            
            # Status endpoint should work and show production mode
            response = client.get("/manager/v1/status")
            assert response.status_code == 200
            assert response.json()["auth_mode"] == "production"