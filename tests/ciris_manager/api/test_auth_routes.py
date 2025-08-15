"""Tests for authentication routes."""

import os
from unittest.mock import Mock, AsyncMock, patch
import pytest
from fastapi import HTTPException, Request

from ciris_manager.api.auth_routes import (
    init_auth_service,
    get_auth_service,
    _get_callback_url,
    _get_redirect_uri,
    create_auth_routes,
    get_current_user_dependency,
)
from ciris_manager.api.auth_service import AuthService, OAuthProvider


class TestAuthServiceInitialization:
    """Test auth service initialization."""

    @patch.dict(os.environ, {"CIRIS_DEV_MODE": "false"})
    @patch("ciris_manager.api.auth_routes.GoogleOAuthProvider")
    @patch("ciris_manager.api.auth_routes.SQLiteUserStore")
    def test_init_auth_service_production(self, mock_user_store, mock_oauth_provider):
        """Test auth service initialization in production mode."""
        # Setup mocks
        mock_provider = Mock(spec=OAuthProvider)
        mock_oauth_provider.return_value = mock_provider
        mock_store = Mock()
        mock_user_store.return_value = mock_store

        # Initialize service
        service = init_auth_service(
            google_client_id="test-client-id",
            google_client_secret="test-client-secret",
            jwt_secret="test-secret",
        )

        # Verify
        assert isinstance(service, AuthService)
        mock_oauth_provider.assert_called_once_with(
            client_id="test-client-id", client_secret="test-client-secret", hd_domain="ciris.ai"
        )
        mock_user_store.assert_called_once()

    @patch.dict(os.environ, {"CIRIS_DEV_MODE": "true"})
    @patch("ciris_manager.api.auth_routes.MockOAuthProvider")
    @patch("ciris_manager.api.auth_routes.SQLiteUserStore")
    def test_init_auth_service_development(self, mock_user_store, mock_oauth_provider):
        """Test auth service initialization in development mode."""
        # Setup mocks
        mock_provider = Mock(spec=OAuthProvider)
        mock_oauth_provider.return_value = mock_provider
        mock_store = Mock()
        mock_user_store.return_value = mock_store

        # Initialize service
        service = init_auth_service()

        # Verify mock provider is used
        assert isinstance(service, AuthService)
        mock_oauth_provider.assert_called_once()

    def test_init_auth_service_no_credentials(self):
        """Test auth service initialization without credentials."""
        with patch.dict(os.environ, {}, clear=True):
            service = init_auth_service()
            assert service is None

    @patch("ciris_manager.api.auth_routes._auth_service", None)
    def test_get_auth_service_not_initialized(self):
        """Test getting auth service when not initialized."""
        with pytest.raises(RuntimeError, match="Auth service not initialized"):
            get_auth_service()


class TestURLHelpers:
    """Test URL helper functions."""

    def test_get_callback_url_localhost(self):
        """Test callback URL generation for localhost."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.hostname = "localhost"

        url = _get_callback_url(request)
        assert url == "http://localhost:8888/manager/v1/oauth/callback"

    def test_get_callback_url_production(self):
        """Test callback URL generation for production."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.hostname = "agents.ciris.ai"

        url = _get_callback_url(request)
        assert url == "https://agents.ciris.ai/manager/v1/oauth/callback"

    def test_get_redirect_uri_with_custom(self):
        """Test redirect URI with custom parameter."""
        request = Mock(spec=Request)
        uri = _get_redirect_uri(request, "/custom/path")
        assert uri == "/custom/path"

    def test_get_redirect_uri_default(self):
        """Test redirect URI default."""
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.scheme = "https"
        request.url.netloc = "example.com"

        uri = _get_redirect_uri(request, None)
        assert uri == "https://example.com/manager/"


class TestAuthRoutes:
    """Test authentication routes."""

    @pytest.fixture
    def mock_auth_service(self):
        """Create mock auth service."""
        from ciris_manager.api.auth_service import AuthService

        # Create mock auth service with AsyncMock for async methods
        service = Mock(spec=AuthService)
        service.initiate_oauth_flow = AsyncMock(
            return_value=("state123", "https://oauth.example.com/auth")
        )
        service.handle_oauth_callback = AsyncMock(
            return_value={"access_token": "jwt-token-123", "redirect_uri": "/dashboard"}
        )
        service.get_current_user = Mock(
            return_value={"email": "test@example.com", "name": "Test User", "id": "user123"}
        )
        service.logout_user = Mock()
        return service

    @pytest.fixture
    def app(self, mock_auth_service):
        """Create test app with auth routes."""
        from fastapi import FastAPI
        from ciris_manager.api.auth_routes import get_auth_service

        app = FastAPI()

        # Override the dependency using FastAPI's dependency injection
        def override_auth_service():
            return mock_auth_service

        app.dependency_overrides[get_auth_service] = override_auth_service

        # Create and include routes with the correct prefix
        router = create_auth_routes()
        app.include_router(router, prefix="/manager/v1")

        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        from fastapi.testclient import TestClient

        return TestClient(app)

    def test_login_route(self, client, mock_auth_service, app):
        """Test login route."""
        # Make request - explicitly don't follow redirects
        response = client.get("/manager/v1/oauth/login", follow_redirects=False)

        # Verify redirect
        assert response.status_code in [302, 307]
        assert "oauth.example.com" in response.headers["location"]

        # Verify the mock was called
        mock_auth_service.initiate_oauth_flow.assert_called_once()

    def test_login_route_with_redirect(self, client, mock_auth_service):
        """Test login route with redirect URI."""
        # Make request
        response = client.get(
            "/manager/v1/oauth/login?redirect_uri=/dashboard", follow_redirects=False
        )

        # Verify
        assert response.status_code in [302, 307]
        assert "oauth.example.com" in response.headers["location"]

        # Verify the redirect URI was passed through
        call_args = mock_auth_service.initiate_oauth_flow.call_args
        assert "/dashboard" in str(call_args)

    def test_callback_route_success(self, client, mock_auth_service):
        """Test OAuth callback with successful authentication."""
        # Make request
        response = client.get(
            "/manager/v1/oauth/callback?code=auth123&state=state123", follow_redirects=False
        )

        # Verify redirect and cookie set
        assert response.status_code in [302, 307]
        assert "token=jwt-token-123" in response.headers["location"]
        assert "manager_token" in response.cookies

        # Verify the mock was called with correct arguments
        mock_auth_service.handle_oauth_callback.assert_called_once_with("auth123", "state123")

    def test_callback_route_error(self, client, mock_auth_service):
        """Test OAuth callback with error."""
        # Setup mock to raise error
        mock_auth_service.handle_oauth_callback.side_effect = ValueError("Invalid state")

        # Make request
        response = client.get(
            "/manager/v1/oauth/callback?code=auth123&state=invalid", follow_redirects=False
        )

        # Verify error response
        assert response.status_code == 400
        assert "Invalid state" in response.json()["detail"]

    def test_callback_route_exception(self, client, mock_auth_service):
        """Test OAuth callback with exception."""
        # Setup mock to raise exception
        mock_auth_service.handle_oauth_callback.side_effect = Exception("OAuth failed")

        # Make request
        response = client.get(
            "/manager/v1/oauth/callback?code=auth123&state=state123", follow_redirects=False
        )

        # Verify error response
        assert response.status_code == 500
        assert "Authentication failed" in response.json()["detail"]

    def test_logout_route(self, client, mock_auth_service):
        """Test logout route."""
        # Make request with cookie
        response = client.post(
            "/manager/v1/oauth/logout",
            cookies={"manager_token": "test-token"},
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "Logged out successfully" in data["message"]

    def test_user_info_route(self, client, mock_auth_service):
        """Test user info route."""
        # Setup mock
        mock_user = {"email": "test@example.com", "name": "Test User", "id": "user123"}
        mock_auth_service.get_current_user.return_value = mock_user

        # Make request with auth header
        response = client.get(
            "/manager/v1/oauth/user",
            headers={"Authorization": "Bearer test-token"},
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == "test@example.com"

    def test_user_info_route_unauthorized(self, client, mock_auth_service):
        """Test user info route without authentication."""
        # Setup mock to return None
        mock_auth_service.get_current_user.return_value = None

        # Make request without auth
        response = client.get("/manager/v1/oauth/user")

        # Verify unauthorized
        assert response.status_code == 401


class TestAuthDependency:
    """Test authentication dependency."""

    def test_get_current_user_with_bearer_token(self):
        """Test getting current user with bearer token."""
        # Setup mock request
        request = Mock(spec=Request)
        request.cookies = {}

        # Setup mock auth service
        mock_service = Mock(spec=AuthService)
        mock_user = {"id": "user123", "email": "test@example.com"}
        mock_service.get_current_user.return_value = mock_user

        with patch("ciris_manager.api.auth_routes.get_auth_service", return_value=mock_service):
            # get_current_user_dependency is not async, it's a regular function
            user = get_current_user_dependency(
                request, authorization="Bearer test-token", auth_service=mock_service
            )
            assert user == mock_user
            mock_service.get_current_user.assert_called_with("Bearer test-token")

    def test_get_current_user_with_cookie(self):
        """Test getting current user with cookie."""
        # Setup mock request
        request = Mock(spec=Request)
        request.cookies = {"manager_token": "cookie-token"}

        # Setup mock auth service
        mock_service = Mock(spec=AuthService)
        mock_user = {"id": "user123", "email": "test@example.com"}
        # First call returns None (no auth header), second returns user (cookie)
        mock_service.get_current_user.side_effect = [None, mock_user]

        with patch("ciris_manager.api.auth_routes.get_auth_service", return_value=mock_service):
            # get_current_user_dependency is not async
            user = get_current_user_dependency(
                request, authorization=None, auth_service=mock_service
            )
            assert user == mock_user
            # Should be called twice - once for header, once for cookie
            assert mock_service.get_current_user.call_count == 2
            mock_service.get_current_user.assert_any_call("Bearer cookie-token")

    def test_get_current_user_no_auth(self):
        """Test getting current user without authentication."""
        # Setup mock request
        request = Mock(spec=Request)
        request.cookies = {}

        # Setup mock auth service
        mock_service = Mock(spec=AuthService)
        mock_service.get_current_user.return_value = None

        with pytest.raises(HTTPException) as exc:
            get_current_user_dependency(request, authorization=None, auth_service=mock_service)
        assert exc.value.status_code == 401
        assert "Not authenticated" in str(exc.value.detail)

    def test_get_current_user_no_service(self):
        """Test getting current user when service not configured."""
        request = Mock(spec=Request)

        with patch("ciris_manager.api.auth_routes.get_auth_service", return_value=None):
            with pytest.raises(HTTPException) as exc:
                get_current_user_dependency(
                    request, authorization="Bearer token", auth_service=None
                )
            assert exc.value.status_code == 500
            assert "OAuth not configured" in str(exc.value.detail)
