"""
Unit tests for admin password security during agent creation.

Tests the automatic password randomization and secure password setting via API.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import json

from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.agent_registry import AgentRegistry


@pytest.fixture
def mock_config(tmp_path):
    """Create a test configuration."""
    config = CIRISManagerConfig()
    config.manager.agents_directory = str(tmp_path / "agents")
    config.manager.templates_directory = str(tmp_path / "templates")
    config.manager.manifest_path = str(tmp_path / "manifest.yaml")
    config.nginx.config_dir = str(tmp_path / "nginx")
    config.ports.start = 8000
    config.ports.end = 9000
    return config


@pytest.fixture
def mock_manager():
    """Create a minimal mock manager for testing password methods."""
    manager = Mock()
    manager._generate_admin_password = CIRISManager._generate_admin_password.__get__(manager)
    manager._generate_service_token = CIRISManager._generate_service_token.__get__(manager)
    manager._set_agent_admin_password = CIRISManager._set_agent_admin_password.__get__(manager)

    # Mock docker_client
    mock_docker_client = Mock()
    mock_server_config = Mock()
    mock_server_config.vpc_ip = "10.0.0.5"
    mock_server_config.hostname = "remote.example.com"
    mock_docker_client.get_server_config = Mock(return_value=mock_server_config)
    manager.docker_client = mock_docker_client

    return manager


class TestAdminPasswordGeneration:
    """Test admin password generation."""

    def test_generate_admin_password_creates_secure_password(self, mock_manager):
        """Test that generated passwords are secure and random."""
        password1 = mock_manager._generate_admin_password()
        password2 = mock_manager._generate_admin_password()

        # Passwords should be different (random)
        assert password1 != password2

        # Passwords should be reasonably long (URL-safe base64 of 24 bytes = ~32 chars)
        assert len(password1) >= 30
        assert len(password2) >= 30

        # Passwords should be URL-safe (no special characters that need encoding)
        assert all(c.isalnum() or c in "-_" for c in password1)
        assert all(c.isalnum() or c in "-_" for c in password2)

    def test_generate_admin_password_entropy(self, mock_manager):
        """Test that generated passwords have high entropy."""
        passwords = [mock_manager._generate_admin_password() for _ in range(100)]

        # All passwords should be unique
        assert len(set(passwords)) == 100

        # Passwords should have good character variety
        all_chars = "".join(passwords)
        unique_chars = len(set(all_chars))
        assert unique_chars >= 60  # Should use most of the URL-safe alphabet


class TestSetAdminPassword:
    """Test setting admin password via agent API."""

    @pytest.mark.asyncio
    async def test_set_admin_password_success(self, mock_manager):
        """Test successful password change via API."""
        agent_id = "test-agent"
        port = 8080
        new_password = "new-secure-password-123"

        # Mock httpx client
        mock_client = AsyncMock()
        mock_login_response = Mock()  # Use Mock, not AsyncMock for the response
        mock_login_response.status_code = 200
        mock_login_response.json = Mock(
            return_value={
                "access_token": "test-session-token",
                "user_id": "admin-user-id",
            }
        )

        mock_password_response = Mock()  # Use Mock, not AsyncMock
        mock_password_response.status_code = 200

        mock_client.post.return_value = mock_login_response
        mock_client.put.return_value = mock_password_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            await mock_manager._set_agent_admin_password(agent_id, port, new_password)

            # Verify login was called with default credentials
            mock_client.post.assert_called_once()
            login_call = mock_client.post.call_args
            assert "ciris_admin_password" in str(login_call)

            # Verify password change was called with new password
            mock_client.put.assert_called_once()
            password_call = mock_client.put.call_args
            assert new_password in str(password_call)
            assert "Bearer test-session-token" in str(password_call)

    @pytest.mark.asyncio
    async def test_set_admin_password_login_failure(self, mock_manager):
        """Test handling of login failure."""
        agent_id = "test-agent"
        port = 8080
        new_password = "new-password"

        # Mock httpx client with failed login
        mock_client = AsyncMock()
        mock_login_response = Mock()
        mock_login_response.status_code = 401
        mock_login_response.text = "Unauthorized"
        mock_client.post.return_value = mock_login_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with pytest.raises(RuntimeError) as exc_info:
                await mock_manager._set_agent_admin_password(agent_id, port, new_password)

            assert "Login failed: 401" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_set_admin_password_change_failure(self, mock_manager):
        """Test handling of password change failure."""
        agent_id = "test-agent"
        port = 8080
        new_password = "new-password"

        # Mock successful login but failed password change
        mock_client = AsyncMock()
        mock_login_response = Mock()
        mock_login_response.status_code = 200
        mock_login_response.json = Mock(
            return_value={
                "access_token": "test-token",
                "user_id": "admin-id",
            }
        )

        mock_password_response = Mock()
        mock_password_response.status_code = 400
        mock_password_response.text = "Invalid password"

        mock_client.post.return_value = mock_login_response
        mock_client.put.return_value = mock_password_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            with pytest.raises(RuntimeError) as exc_info:
                await mock_manager._set_agent_admin_password(agent_id, port, new_password)

            assert "Password change failed: 400" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_set_admin_password_remote_server(self, mock_manager):
        """Test password change for remote server."""
        agent_id = "remote-agent"
        port = 8000
        new_password = "new-password"
        server_id = "remote-server"

        # Mock httpx client
        mock_client = AsyncMock()
        mock_login_response = Mock()
        mock_login_response.status_code = 200
        mock_login_response.json = Mock(
            return_value={
                "access_token": "token",
                "user_id": "admin",
            }
        )
        mock_password_response = Mock()
        mock_password_response.status_code = 200

        mock_client.post.return_value = mock_login_response
        mock_client.put.return_value = mock_password_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__.return_value = mock_client

            await mock_manager._set_agent_admin_password(agent_id, port, new_password, server_id)

            # Verify correct URL was used (VPC IP, not localhost)
            login_call = mock_client.post.call_args
            assert "10.0.0.5" in str(login_call[0][0])


class TestPasswordEncryptionStorage:
    """Test password encryption and storage in registry."""

    def test_admin_password_encrypted_in_registry(self, tmp_path):
        """Test that admin passwords are encrypted before storage."""
        from ciris_manager.crypto import get_token_encryption

        encryption = get_token_encryption()

        # Create a test password
        plain_password = "test-password-123"
        encrypted = encryption.encrypt_token(plain_password)

        # Encrypted should be different from plain
        assert encrypted != plain_password

        # Should be able to decrypt back
        decrypted = encryption.decrypt_token(encrypted)
        assert decrypted == plain_password

    def test_registry_stores_encrypted_password(self, tmp_path):
        """Test that registry stores encrypted admin password."""
        from ciris_manager.crypto import get_token_encryption

        metadata_path = tmp_path / "metadata.json"
        registry = AgentRegistry(metadata_path)

        encryption = get_token_encryption()
        plain_password = "secure-password-abc"
        encrypted_password = encryption.encrypt_token(plain_password)

        # Register agent with encrypted password
        agent = registry.register_agent(
            agent_id="test-agent",
            name="Test Agent",
            port=8080,
            template="test",
            compose_file="/path/to/compose.yml",
            service_token="encrypted-token",
            admin_password=encrypted_password,
        )

        assert agent.admin_password == encrypted_password

        # Verify it's stored encrypted in file
        with open(metadata_path) as f:
            data = json.load(f)

        stored_password = data["agents"]["test-agent"]["admin_password"]
        assert stored_password == encrypted_password
        assert stored_password != plain_password

        # Verify we can decrypt it
        decrypted = encryption.decrypt_token(stored_password)
        assert decrypted == plain_password


class TestCreateAgentIntegration:
    """Integration tests for agent creation with password security."""

    def test_create_agent_password_flow(self):
        """Test the logical flow of password generation and setting."""
        # Create a minimal mock for the manager
        mock_mgr = Mock()
        mock_mgr._generate_admin_password = CIRISManager._generate_admin_password.__get__(mock_mgr)

        # Test password generation
        password = mock_mgr._generate_admin_password()
        assert len(password) >= 30
        assert password != "ciris_admin_password"

        # Test that the password would be used in agent creation
        # This just verifies the logical flow without full integration
        assert password  # Password is generated
        # In real flow: password is encrypted and stored in registry
        # In real flow: password is set via agent API after container starts


class TestBackwardCompatibility:
    """Test backward compatibility with existing agents."""

    def test_registry_loads_agents_without_password(self, tmp_path):
        """Test that registry can load old agents without admin_password field."""
        metadata_path = tmp_path / "metadata.json"

        # Create metadata file with agent that has no admin_password
        metadata = {
            "version": "1.0",
            "updated_at": "2024-01-01T00:00:00Z",
            "agents": {
                "old-agent": {
                    "name": "Old Agent",
                    "port": 8080,
                    "template": "test",
                    "compose_file": "/path/to/compose.yml",
                    "created_at": "2024-01-01T00:00:00Z",
                    "metadata": {},
                    "service_token": "encrypted-token",
                    # No admin_password field
                }
            },
        }

        with open(metadata_path, "w") as f:
            json.dump(metadata, f)

        # Should load without error
        registry = AgentRegistry(metadata_path)
        agent = registry.get_agent("old-agent")

        assert agent is not None
        assert agent.admin_password is None  # Should gracefully handle missing field


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
