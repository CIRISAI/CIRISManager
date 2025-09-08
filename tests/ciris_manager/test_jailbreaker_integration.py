"""
Integration test for jailbreaker functionality.

This test demonstrates the full OAuth flow and agent reset process.
It uses mocked external services but tests the actual integration.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ciris_manager.jailbreaker import (
    JailbreakerConfig,
    JailbreakerService,
    create_jailbreaker_routes,
)


class TestJailbreakerIntegration:
    """Integration tests for jailbreaker functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = Path(tempfile.mkdtemp())

        # Create test agent directory structure
        agent_dir = temp_dir / "echo-nemesis-v2tyey"
        agent_dir.mkdir()
        data_dir = agent_dir / "data"
        data_dir.mkdir()
        (data_dir / "test_conversation.json").write_text('{"messages": ["test"]}')
        (data_dir / "test_memory.db").write_text("dummy database content")

        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def config(self):
        """Create test config."""
        return JailbreakerConfig(
            discord_client_id="test_client_id",
            discord_client_secret="test_secret",
            discord_guild_id="test_guild",
            jailbreak_role_name="jailbreak",
            target_agent_id="echo-nemesis-v2tyey",
            global_rate_limit="1/30seconds",  # Short for testing
            user_rate_limit="1/60seconds",
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
            config=config, agent_dir=temp_dir, container_manager=mock_container_manager
        )

    @pytest.fixture
    def app(self, jailbreaker_service):
        """Create test FastAPI app."""
        app = FastAPI()
        router = create_jailbreaker_routes(jailbreaker_service)
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    @pytest.mark.asyncio
    async def test_full_oauth_flow(self, client, jailbreaker_service):
        """Test the full OAuth flow from start to finish."""

        # Step 1: Initialize OAuth
        init_response = client.get("/jailbreaker/oauth/init?state=custom_test_state")
        assert init_response.status_code == 200
        init_data = init_response.json()

        assert "discord.com/api/oauth2/authorize" in init_data["auth_url"]
        assert init_data["state"] == "custom_test_state"
        assert "client_id=test_client_id" in init_data["auth_url"]

        # Step 2: Mock successful OAuth callback
        with patch.object(
            jailbreaker_service.discord_client, "exchange_code_for_token"
        ) as mock_exchange:
            with patch.object(
                jailbreaker_service.discord_client, "verify_jailbreak_permission"
            ) as mock_verify:
                from ciris_manager.jailbreaker.models import DiscordUser

                mock_exchange.return_value = "mock_access_token"
                mock_user = DiscordUser(id="123456789", username="testuser", discriminator="0001")
                mock_verify.return_value = (True, mock_user)

                callback_response = client.post(
                    "/jailbreaker/oauth/callback",
                    json={"code": "oauth_auth_code", "state": "custom_test_state"},
                )

                assert callback_response.status_code == 200
                callback_data = callback_response.json()
                assert callback_data["access_token"] == "mock_access_token"
                assert callback_data["message"] == "Authentication successful"

                # Step 3: Use access token to reset agent
                with patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value.returncode = 0
                    reset_response = client.post(
                        "/jailbreaker/reset", json={"access_token": "mock_access_token"}
                    )

                assert reset_response.status_code == 200
                reset_data = reset_response.json()
                assert reset_data["status"] == "success"
                assert reset_data["user_id"] == "123456789"
                assert reset_data["agent_id"] == "echo-nemesis-v2tyey"
                assert "reset successfully" in reset_data["message"]

    @pytest.mark.asyncio
    async def test_unauthorized_user_flow(self, client, jailbreaker_service):
        """Test flow with unauthorized user."""

        with patch.object(
            jailbreaker_service.discord_client, "exchange_code_for_token"
        ) as mock_exchange:
            with patch.object(
                jailbreaker_service.discord_client, "verify_jailbreak_permission"
            ) as mock_verify:
                mock_exchange.return_value = "unauthorized_token"
                mock_verify.return_value = (False, None)  # No permission

                # OAuth callback should fail
                callback_response = client.post(
                    "/jailbreaker/oauth/callback",
                    json={"code": "oauth_auth_code", "state": "test_state"},
                )

                assert callback_response.status_code == 403
                assert "does not have jailbreak permissions" in callback_response.json()["detail"]

    @pytest.mark.asyncio
    async def test_rate_limiting_flow(self, client, jailbreaker_service, temp_dir):
        """Test rate limiting across multiple requests."""

        with patch.object(
            jailbreaker_service.discord_client, "verify_jailbreak_permission"
        ) as mock_verify:
            from ciris_manager.jailbreaker.models import DiscordUser

            mock_user = DiscordUser(id="rate_test_user", username="ratetest", discriminator="0001")
            mock_verify.return_value = (True, mock_user)

            # First reset should succeed
            with patch("subprocess.run") as mock_subprocess:
                mock_subprocess.return_value.returncode = 0
                reset_response1 = client.post(
                    "/jailbreaker/reset", json={"access_token": "test_token"}
                )

            assert reset_response1.status_code == 200
            assert reset_response1.json()["status"] == "success"

            # Second reset should be rate limited
            reset_response2 = client.post("/jailbreaker/reset", json={"access_token": "test_token"})

            assert reset_response2.status_code == 429
            assert "Rate limit exceeded" in reset_response2.json()["detail"]

    @pytest.mark.asyncio
    async def test_status_endpoint(self, client):
        """Test the status endpoint."""
        response = client.get("/jailbreaker/status")

        assert response.status_code == 200
        data = response.json()

        # Verify status structure
        assert "global_limit_seconds" in data
        assert "user_limit_seconds" in data
        assert "tracked_users" in data
        assert data["global_limit_seconds"] == 30  # From config
        assert data["user_limit_seconds"] == 60  # From config

    @pytest.mark.asyncio
    async def test_status_endpoint_with_user(self, client, jailbreaker_service):
        """Test the status endpoint with user-specific data."""

        with patch.object(
            jailbreaker_service.discord_client, "verify_jailbreak_permission"
        ) as mock_verify:
            from ciris_manager.jailbreaker.models import DiscordUser

            mock_user = DiscordUser(
                id="status_test_user", username="statustest", discriminator="0001"
            )
            mock_verify.return_value = (True, mock_user)

            # Perform a reset to create user data
            with patch("subprocess.run") as mock_subprocess:
                mock_subprocess.return_value.returncode = 0
                client.post("/jailbreaker/reset", json={"access_token": "test_token"})

            # Check status with user ID
            response = client.get("/jailbreaker/status?user_id=status_test_user")

            assert response.status_code == 200
            data = response.json()

            assert "user_next_reset" in data
            assert data["user_next_reset"] is not None  # Should have a timestamp

    @pytest.mark.skip(reason="Test needs updating for new sudo-based directory creation")
    @pytest.mark.asyncio
    async def test_data_directory_cleanup(self, client, jailbreaker_service, temp_dir):
        """Test that data directory is properly cleaned during reset."""

        with patch.object(
            jailbreaker_service.discord_client, "verify_jailbreak_permission"
        ) as mock_verify:
            from ciris_manager.jailbreaker.models import DiscordUser

            mock_user = DiscordUser(id="cleanup_test", username="cleanup", discriminator="0001")
            mock_verify.return_value = (True, mock_user)

            # Verify test files exist before reset
            agent_dir = temp_dir / "echo-nemesis-v2tyey"
            data_dir = agent_dir / "data"

            assert data_dir.exists()
            assert (data_dir / "test_conversation.json").exists()
            assert (data_dir / "test_memory.db").exists()

            # Perform reset
            with patch("subprocess.run") as mock_subprocess:
                mock_subprocess.return_value.returncode = 0
                response = client.post("/jailbreaker/reset", json={"access_token": "test_token"})

            assert response.status_code == 200

            # Verify data directory was recreated empty (new behavior)
            assert data_dir.exists()
            assert list(data_dir.iterdir()) == []  # Should be empty

            # Verify container operations were called
            jailbreaker_service.container_manager.stop_container.assert_called_once_with(
                "ciris-echo-nemesis-v2tyey"
            )
            jailbreaker_service.container_manager.start_container.assert_called_once_with(
                "ciris-echo-nemesis-v2tyey"
            )

    @pytest.mark.asyncio
    async def test_cleanup_endpoint(self, client):
        """Test the cleanup endpoint."""
        response = client.post("/jailbreaker/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Rate limiter cleanup completed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
