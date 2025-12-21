"""Tests for OAuth Device Flow routes."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock
from datetime import datetime, timezone, timedelta

from ciris_manager.api.device_auth_routes import (
    create_device_auth_routes,
    generate_user_code,
    _device_codes,
    _user_codes,
)
from ciris_manager.api.auth_service import AuthService


@pytest.fixture
def auth_service():
    """Mock auth service."""
    service = Mock(spec=AuthService)
    service.jwt_expiration_hours = 24
    service.create_jwt_token = Mock(return_value="test-jwt-token")
    service.get_current_user = Mock(
        return_value={
            "email": "test@ciris.ai",
            "name": "Test User",
            "picture": "",
            "hd": "ciris.ai",
        }
    )
    service.oauth_provider = Mock()
    service.oauth_provider.__class__.__name__ = "GoogleOAuthProvider"
    return service


@pytest.fixture
def client(auth_service):
    """Test client with auth service."""
    from fastapi import FastAPI

    app = FastAPI()

    # Override dependency
    from ciris_manager.api.device_auth_routes import get_auth_service

    app.dependency_overrides[get_auth_service] = lambda: auth_service

    router = create_device_auth_routes()
    app.include_router(router)

    # Clear storage before each test
    _device_codes.clear()
    _user_codes.clear()

    return TestClient(app)


class TestDeviceAuthRoutes:
    """Test device authentication flow."""

    def test_generate_user_code(self):
        """Test user code generation."""
        code = generate_user_code()
        assert len(code) == 9  # XXXX-XXXX
        assert code[4] == "-"
        assert code[:4].isalnum()
        assert code[5:].isalnum()

    def test_request_device_code(self, client):
        """Test device code request."""
        response = client.post(
            "/device/code", json={"client_id": "ciris-cli", "scope": "manager:full"}
        )

        assert response.status_code == 200
        data = response.json()

        assert "device_code" in data
        assert "user_code" in data
        assert "verification_uri" in data
        assert "verification_uri_complete" in data
        assert data["expires_in"] == 600
        assert data["interval"] == 5

        # Check storage
        assert data["device_code"] in _device_codes
        assert data["user_code"] in _user_codes

    def test_device_verification_page(self, client):
        """Test device verification page."""
        response = client.get("/device")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Device Authorization" in response.text

    def test_device_verification_page_with_code(self, client):
        """Test device verification page with pre-filled code."""
        response = client.get("/device?code=TEST-CODE")

        assert response.status_code == 200
        assert "TEST-CODE" in response.text

    def test_poll_token_pending(self, client):
        """Test polling while authorization is pending."""
        # Request device code
        code_response = client.post("/device/code", json={})
        device_code = code_response.json()["device_code"]

        # Poll for token
        response = client.post(
            "/device/token", json={"device_code": device_code, "client_id": "ciris-cli"}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "authorization_pending"

    def test_poll_token_invalid_code(self, client):
        """Test polling with invalid device code."""
        response = client.post(
            "/device/token", json={"device_code": "invalid-code", "client_id": "ciris-cli"}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "invalid_grant"

    def test_poll_token_expired(self, client):
        """Test polling with expired device code."""
        # Request device code
        code_response = client.post("/device/code", json={})
        device_code = code_response.json()["device_code"]

        # Expire the code
        _device_codes[device_code]["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)

        # Poll for token
        response = client.post(
            "/device/token", json={"device_code": device_code, "client_id": "ciris-cli"}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "expired_token"

    def test_verify_device_code_not_authenticated(self, client, auth_service):
        """Test device verification without authentication."""
        auth_service.get_current_user.return_value = None

        response = client.post("/device/verify", json={"user_code": "TEST-CODE"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"

    def test_verify_device_code_invalid(self, client):
        """Test device verification with invalid code."""
        response = client.post(
            "/device/verify", json={"user_code": "INVALID"}, cookies={"manager_token": "test-token"}
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid code"

    def test_complete_flow(self, client, auth_service):
        """Test complete device auth flow."""
        # 1. Request device code
        code_response = client.post("/device/code", json={})
        assert code_response.status_code == 200

        device_data = code_response.json()
        device_code = device_data["device_code"]
        user_code = device_data["user_code"]

        # 2. Verify device code (simulate user authorization)
        verify_response = client.post(
            "/device/verify", json={"user_code": user_code}, cookies={"manager_token": "test-token"}
        )
        assert verify_response.status_code == 200

        # 3. Poll for token
        token_response = client.post(
            "/device/token", json={"device_code": device_code, "client_id": "ciris-cli"}
        )

        assert token_response.status_code == 200
        token_data = token_response.json()

        assert token_data["access_token"] == "test-jwt-token"
        assert token_data["token_type"] == "Bearer"
        assert token_data["expires_in"] == 86400  # 24 hours

        # Check codes are cleaned up
        assert device_code not in _device_codes
        assert user_code not in _user_codes

    def test_verify_non_ciris_email(self, client, auth_service):
        """Test verification with non-@ciris.ai email."""
        auth_service.get_current_user.return_value = {
            "email": "test@example.com",
            "name": "Test User",
        }

        # Request device code
        code_response = client.post("/device/code", json={})
        user_code = code_response.json()["user_code"]

        # Try to verify
        response = client.post(
            "/device/verify", json={"user_code": user_code}, cookies={"manager_token": "test-token"}
        )

        assert response.status_code == 403
        assert "@ciris.ai users" in response.json()["detail"]
