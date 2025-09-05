"""
Unit tests for jailbreaker functionality.
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ciris_manager.jailbreaker.models import (
    JailbreakerConfig, 
    ResetResult, 
    ResetStatus,
    DiscordUser
)
from ciris_manager.jailbreaker.rate_limiter import RateLimiter, parse_rate_limit_string
from ciris_manager.jailbreaker.discord_client import DiscordAuthClient
from ciris_manager.jailbreaker.service import JailbreakerService
from ciris_manager.jailbreaker.routes import create_jailbreaker_routes


class TestRateLimiter:
    """Test rate limiting functionality."""
    
    @pytest.fixture
    def rate_limiter(self):
        """Create a rate limiter for testing."""
        return RateLimiter(global_limit_seconds=10, user_limit_seconds=30)
    
    @pytest.mark.asyncio
    async def test_rate_limit_parsing(self):
        """Test rate limit string parsing."""
        assert parse_rate_limit_string("1/5minutes") == 300
        assert parse_rate_limit_string("1/hour") == 3600
        assert parse_rate_limit_string("1/30seconds") == 30
        assert parse_rate_limit_string("1/2hours") == 7200
        
        with pytest.raises(ValueError):
            parse_rate_limit_string("invalid")
            
        with pytest.raises(ValueError):
            parse_rate_limit_string("2/hour")  # Only 1/period supported
    
    @pytest.mark.asyncio
    async def test_first_request_allowed(self, rate_limiter):
        """Test first request is always allowed."""
        allowed, next_allowed = await rate_limiter.check_rate_limit("user1")
        assert allowed is True
        assert next_allowed is None
    
    @pytest.mark.asyncio
    async def test_global_rate_limit(self, rate_limiter):
        """Test global rate limiting."""
        # First request
        allowed, _ = await rate_limiter.check_rate_limit("user1")
        assert allowed is True
        
        await rate_limiter.record_reset("user1")
        
        # Second request from different user should be blocked by global limit
        allowed, next_allowed = await rate_limiter.check_rate_limit("user2")
        assert allowed is False
        assert next_allowed is not None
    
    @pytest.mark.asyncio
    async def test_user_rate_limit(self, rate_limiter):
        """Test per-user rate limiting."""
        # First request
        allowed, _ = await rate_limiter.check_rate_limit("user1")
        assert allowed is True
        await rate_limiter.record_reset("user1")
        
        # Wait for global limit to expire but user limit still active
        await asyncio.sleep(0.1)  # Simulate time passing
        rate_limiter._last_global_reset -= 11  # Manually expire global limit
        
        # Same user should still be blocked
        allowed, next_allowed = await rate_limiter.check_rate_limit("user1")
        assert allowed is False
        assert next_allowed is not None
    
    @pytest.mark.asyncio
    async def test_cleanup(self, rate_limiter):
        """Test cleanup of old entries."""
        await rate_limiter.record_reset("user1")
        assert "user1" in rate_limiter._user_resets
        
        # Manually age the entry
        rate_limiter._user_resets["user1"] -= rate_limiter.user_limit_seconds * 3
        
        await rate_limiter.cleanup_old_entries()
        assert "user1" not in rate_limiter._user_resets


class TestJailbreakerConfig:
    """Test jailbreaker configuration."""
    
    def test_config_creation(self):
        """Test config creation with defaults."""
        config = JailbreakerConfig(
            discord_client_id="test_client",
            discord_client_secret="test_secret"
        )
        
        assert config.discord_client_id == "test_client"
        assert config.discord_client_secret == "test_secret"
        assert config.discord_guild_id == "1364300186003968060"
        assert config.jailbreak_role_name == "jailbreak"
        assert config.target_agent_id == "datum"
        assert config.global_rate_limit == "1/5minutes"
        assert config.user_rate_limit == "1/hour"
    
    @patch.dict('os.environ', {
        'DISCORD_CLIENT_ID': 'env_client',
        'DISCORD_CLIENT_SECRET': 'env_secret',
        'DISCORD_GUILD_ID': 'env_guild',
        'JAILBREAK_ROLE_NAME': 'env_role',
        'JAILBREAK_TARGET_AGENT': 'env_agent'
    })
    def test_config_from_env(self):
        """Test config creation from environment variables."""
        config = JailbreakerConfig.from_env()
        
        assert config.discord_client_id == "env_client"
        assert config.discord_client_secret == "env_secret"
        assert config.discord_guild_id == "env_guild"
        assert config.jailbreak_role_name == "env_role"
        assert config.target_agent_id == "env_agent"


class TestDiscordAuthClient:
    """Test Discord OAuth client."""
    
    @pytest.fixture
    def config(self):
        """Create test config."""
        return JailbreakerConfig(
            discord_client_id="test_client",
            discord_client_secret="test_secret"
        )
    
    @pytest.fixture
    def discord_client(self, config):
        """Create Discord client."""
        return DiscordAuthClient(config)
    
    def test_generate_oauth_url(self, discord_client):
        """Test OAuth URL generation."""
        auth_url, state = discord_client.generate_oauth_url()
        
        assert "discord.com/api/oauth2/authorize" in auth_url
        assert "client_id=test_client" in auth_url
        assert "scope=identify" in auth_url and "guilds.members.read" in auth_url
        assert f"state={state}" in auth_url
        assert len(state) > 10  # Should be a secure random string
    
    def test_generate_oauth_url_with_state(self, discord_client):
        """Test OAuth URL generation with provided state."""
        auth_url, returned_state = discord_client.generate_oauth_url("custom_state")
        
        assert "state=custom_state" in auth_url
        assert returned_state == "custom_state"
    
    @pytest.mark.asyncio
    async def test_exchange_code_success(self, discord_client):
        """Test successful token exchange."""
        with patch.object(discord_client._client, 'post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = {"access_token": "test_token"}
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response
            
            token = await discord_client.exchange_code_for_token("test_code")
            assert token == "test_token"
            
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "authorization_code" in str(call_args)
    
    @pytest.mark.asyncio
    async def test_get_current_user(self, discord_client):
        """Test getting current user info."""
        with patch.object(discord_client._client, 'get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "id": "123456789",
                "username": "testuser",
                "discriminator": "1234",
                "avatar": "avatar_hash"
            }
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response
            
            user = await discord_client.get_current_user("test_token")
            
            assert isinstance(user, DiscordUser)
            assert user.id == "123456789"
            assert user.username == "testuser"
            assert user.discriminator == "1234"
            assert user.avatar == "avatar_hash"


class TestJailbreakerService:
    """Test jailbreaker service."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def config(self):
        """Create test config."""
        return JailbreakerConfig(
            discord_client_id="test_client",
            discord_client_secret="test_secret",
            target_agent_id="test-agent"
        )
    
    @pytest.fixture
    def mock_container_manager(self):
        """Create mock container manager."""
        manager = Mock()
        manager.stop_container = AsyncMock()
        manager.start_container = AsyncMock()
        return manager
    
    @pytest.fixture
    def jailbreaker_service(self, config, temp_dir, mock_container_manager):
        """Create jailbreaker service."""
        return JailbreakerService(
            config=config,
            agent_dir=temp_dir,
            container_manager=mock_container_manager
        )
    
    @pytest.mark.asyncio
    async def test_verify_access_token_success(self, jailbreaker_service):
        """Test successful access token verification."""
        with patch.object(jailbreaker_service.discord_client, 'verify_jailbreak_permission') as mock_verify:
            mock_user = DiscordUser(id="123", username="test", discriminator="0001")
            mock_verify.return_value = (True, mock_user)
            
            has_permission, user_id = await jailbreaker_service.verify_access_token("test_token")
            
            assert has_permission is True
            assert user_id == "123"
    
    @pytest.mark.asyncio
    async def test_verify_access_token_failure(self, jailbreaker_service):
        """Test failed access token verification."""
        with patch.object(jailbreaker_service.discord_client, 'verify_jailbreak_permission') as mock_verify:
            mock_verify.return_value = (False, None)
            
            has_permission, user_id = await jailbreaker_service.verify_access_token("bad_token")
            
            assert has_permission is False
            assert user_id is None
    
    @pytest.mark.asyncio
    async def test_reset_agent_unauthorized(self, jailbreaker_service):
        """Test agent reset with unauthorized user."""
        with patch.object(jailbreaker_service, 'verify_access_token') as mock_verify:
            mock_verify.return_value = (False, None)
            
            result = await jailbreaker_service.reset_agent("bad_token")
            
            assert result.status == ResetStatus.UNAUTHORIZED
            assert "does not have jailbreak permissions" in result.message
    
    @pytest.mark.asyncio
    async def test_reset_agent_rate_limited(self, jailbreaker_service):
        """Test agent reset when rate limited."""
        with patch.object(jailbreaker_service, 'verify_access_token') as mock_verify:
            mock_verify.return_value = (True, "user123")
            
            # Trigger rate limit by recording a reset
            await jailbreaker_service.rate_limiter.record_reset("user123")
            
            result = await jailbreaker_service.reset_agent("test_token")
            
            assert result.status == ResetStatus.RATE_LIMITED
            assert result.user_id == "user123"
            assert result.next_allowed_reset is not None
    
    @pytest.mark.asyncio
    async def test_reset_agent_not_found(self, jailbreaker_service):
        """Test agent reset when agent doesn't exist."""
        with patch.object(jailbreaker_service, 'verify_access_token') as mock_verify:
            mock_verify.return_value = (True, "user123")
            
            # Agent directory doesn't exist
            result = await jailbreaker_service.reset_agent("test_token")
            
            assert result.status == ResetStatus.AGENT_NOT_FOUND
            assert "not found" in result.message
    
    @pytest.mark.asyncio
    async def test_reset_agent_success(self, jailbreaker_service, temp_dir):
        """Test successful agent reset."""
        with patch.object(jailbreaker_service, 'verify_access_token') as mock_verify:
            mock_verify.return_value = (True, "user123")
            
            # Create agent directory and data folder
            agent_dir = temp_dir / "test-agent"
            agent_dir.mkdir()
            data_dir = agent_dir / "data"
            data_dir.mkdir()
            (data_dir / "test_file.txt").write_text("test data")
            
            result = await jailbreaker_service.reset_agent("test_token")
            
            assert result.status == ResetStatus.SUCCESS
            assert result.user_id == "user123"
            assert result.agent_id == "test-agent"
            assert not data_dir.exists()  # Data directory should be wiped


class TestJailbreakerRoutes:
    """Test jailbreaker API routes."""
    
    @pytest.fixture
    def mock_service(self):
        """Create mock jailbreaker service."""
        service = Mock()
        service.generate_oauth_url = Mock(return_value=("https://discord.com/oauth", "state123"))
        service.exchange_code_for_token = AsyncMock(return_value="access_token")
        service.verify_access_token = AsyncMock(return_value=(True, "user123"))
        service.reset_agent = AsyncMock(return_value=ResetResult(
            status=ResetStatus.SUCCESS,
            message="Reset successful",
            user_id="user123",
            agent_id="test-agent"
        ))
        service.get_rate_limit_status = Mock(return_value={
            "global_limit_seconds": 300,
            "user_limit_seconds": 3600,
            "tracked_users": 0,
            "last_global_reset": None,
            "seconds_until_next_global": None
        })
        return service
    
    @pytest.fixture
    def app(self, mock_service):
        """Create test FastAPI app."""
        app = FastAPI()
        router = create_jailbreaker_routes(mock_service)
        app.include_router(router)
        return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)
    
    def test_init_oauth(self, client, mock_service):
        """Test OAuth initialization."""
        response = client.get("/jailbreaker/oauth/init")
        
        assert response.status_code == 200
        data = response.json()
        assert data["auth_url"] == "https://discord.com/oauth"
        assert data["state"] == "state123"
    
    def test_init_oauth_with_state(self, client, mock_service):
        """Test OAuth initialization with custom state."""
        mock_service.generate_oauth_url.return_value = ("https://discord.com/oauth", "custom_state")
        
        response = client.get("/jailbreaker/oauth/init?state=custom_state")
        
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "custom_state"
    
    def test_oauth_callback_success(self, client, mock_service):
        """Test successful OAuth callback."""
        response = client.post("/jailbreaker/oauth/callback", json={
            "code": "oauth_code",
            "state": "state123"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "access_token"
        assert data["message"] == "Authentication successful"
    
    def test_oauth_callback_unauthorized(self, client, mock_service):
        """Test OAuth callback with unauthorized user."""
        mock_service.verify_access_token.return_value = (False, None)
        
        response = client.post("/jailbreaker/oauth/callback", json={
            "code": "oauth_code",
            "state": "state123"
        })
        
        assert response.status_code == 403
        assert "does not have jailbreak permissions" in response.json()["detail"]
    
    def test_reset_agent_success(self, client, mock_service):
        """Test successful agent reset."""
        response = client.post("/jailbreaker/reset", json={
            "access_token": "test_token"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["user_id"] == "user123"
        assert data["agent_id"] == "test-agent"
    
    def test_reset_agent_rate_limited(self, client, mock_service):
        """Test agent reset when rate limited."""
        mock_service.reset_agent.return_value = ResetResult(
            status=ResetStatus.RATE_LIMITED,
            message="Rate limit exceeded",
            user_id="user123",
            agent_id="test-agent",
            next_allowed_reset=1234567890
        )
        
        response = client.post("/jailbreaker/reset", json={
            "access_token": "test_token"
        })
        
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]
    
    def test_get_status(self, client, mock_service):
        """Test getting service status."""
        response = client.get("/jailbreaker/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["global_limit_seconds"] == 300
        assert data["user_limit_seconds"] == 3600
        assert data["tracked_users"] == 0


if __name__ == "__main__":
    pytest.main([__file__])