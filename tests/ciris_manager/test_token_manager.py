"""
Tests for service token management.
"""

import json
from unittest.mock import AsyncMock, Mock, patch
import pytest

from ciris_manager.agent_registry import AgentRegistry, AgentInfo
from ciris_manager.token_manager import TokenManager, TokenStatus, TokenRotationResult


@pytest.fixture
def mock_registry():
    """Create a mock agent registry."""
    registry = Mock(spec=AgentRegistry)

    # Create test agents
    agent1 = AgentInfo(
        agent_id="test-agent-1",
        name="Test Agent 1",
        port=8001,
        template="scout",
        compose_file="/opt/ciris/agents/test-agent-1/docker-compose.yml",
        service_token="gAAAAABhZFNT..." * 10,  # Simulate encrypted token
    )

    agent2 = AgentInfo(
        agent_id="test-agent-2",
        name="Test Agent 2",
        port=8002,
        template="sage",
        compose_file="/opt/ciris/agents/test-agent-2/docker-compose.yml",
        service_token=None,  # No token
    )

    agent3 = AgentInfo(
        agent_id="test-agent-3",
        name="Test Agent 3",
        port=8003,
        template="scout",
        compose_file="/opt/ciris/agents/test-agent-3/docker-compose.yml",
        service_token="short_token",  # Unencrypted token
    )

    registry.list_agents.return_value = [agent1, agent2, agent3]
    registry.get_agent.side_effect = lambda aid: {
        "test-agent-1": agent1,
        "test-agent-2": agent2,
        "test-agent-3": agent3,
    }.get(aid)

    return registry


@pytest.fixture
def token_manager(mock_registry, tmp_path):
    """Create a token manager with mock registry."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    return TokenManager(mock_registry, agents_dir)


@pytest.mark.asyncio
async def test_list_tokens(token_manager, mock_registry):
    """Test listing tokens and their status."""
    with patch.object(token_manager.encryption, "decrypt_token") as mock_decrypt:
        mock_decrypt.return_value = "decrypted_token"

        health_list = await token_manager.list_tokens()

        assert len(health_list) == 3

        # Check each agent's health
        health_by_id = {h.agent_id: h for h in health_list}

        # Agent 1: Valid encrypted token
        assert health_by_id["test-agent-1"].status == TokenStatus.VALID

        # Agent 2: Missing token
        assert health_by_id["test-agent-2"].status == TokenStatus.MISSING
        assert "No service token" in health_by_id["test-agent-2"].error_message

        # Agent 3: Unencrypted token
        assert health_by_id["test-agent-3"].status == TokenStatus.UNENCRYPTED
        assert "unencrypted" in health_by_id["test-agent-3"].error_message


@pytest.mark.asyncio
async def test_verify_token_success(token_manager):
    """Test successful token verification."""
    with patch("ciris_manager.token_manager.get_agent_auth") as mock_get_auth:
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer token"}
        mock_get_auth.return_value = mock_auth

        with patch("ciris_manager.token_manager.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            success, message = await token_manager.verify_token("test-agent-1")

            assert success is True
            assert "successful" in message.lower()


@pytest.mark.asyncio
async def test_verify_token_unauthorized(token_manager):
    """Test token verification with unauthorized response."""
    with patch("ciris_manager.token_manager.get_agent_auth") as mock_get_auth:
        mock_auth = Mock()
        mock_auth.get_auth_headers.return_value = {"Authorization": "Bearer bad_token"}
        mock_get_auth.return_value = mock_auth

        with patch("ciris_manager.token_manager.AsyncClient") as mock_client:
            mock_response = Mock()
            mock_response.status_code = 401

            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value = mock_client_instance

            success, message = await token_manager.verify_token("test-agent-1")

            assert success is False
            assert "401" in message


@pytest.mark.asyncio
async def test_regenerate_token(token_manager, mock_registry, tmp_path):
    """Test token regeneration for an agent."""
    # Create a mock compose file
    compose_file = tmp_path / "test-agent-1" / "docker-compose.yml"
    compose_file.parent.mkdir(parents=True)
    compose_file.write_text("version: '3'")

    mock_registry.update_agent_token = Mock(return_value=True)

    with patch.object(
        token_manager, "_restart_agent_with_token", new_callable=AsyncMock
    ) as mock_restart:
        mock_restart.return_value = True

        with patch.object(token_manager, "verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = (True, "Token verified")

            result = await token_manager.regenerate_token("test-agent-1")

            assert result.success is True
            assert result.new_token_generated is True
            assert result.container_restarted is True
            assert result.auth_verified is True

            # Check that registry was updated
            mock_registry.update_agent_token.assert_called_once()
            args = mock_registry.update_agent_token.call_args[0]
            assert args[0] == "test-agent-1"
            assert len(args[1]) > 100  # Encrypted token should be long


@pytest.mark.asyncio
async def test_recover_tokens_from_containers(token_manager, mock_registry):
    """Test recovering tokens from running containers."""
    with patch("asyncio.create_subprocess_exec") as mock_subprocess:
        # Simulate different container responses
        async def subprocess_side_effect(*args, **kwargs):
            container = args[2] if len(args) > 2 else ""
            mock_proc = AsyncMock()

            if "ciris-test-agent-1" in container:
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(return_value=(b"recovered_token_1", b""))
            elif "ciris-test-agent-2" in container:
                mock_proc.returncode = 1  # Container not running
                mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            else:
                mock_proc.returncode = 0
                mock_proc.communicate = AsyncMock(return_value=(b"recovered_token_3", b""))
            return mock_proc

        mock_subprocess.side_effect = subprocess_side_effect
        mock_registry.update_agent_token = Mock(return_value=True)

        results = await token_manager.recover_tokens_from_containers()

        assert results["test-agent-1"] is True
        assert results["test-agent-2"] is False
        assert results["test-agent-3"] is True

        # Check that tokens were updated
        assert mock_registry.update_agent_token.call_count == 2


@pytest.mark.asyncio
async def test_validate_all_tokens(token_manager, mock_registry):
    """Test validating all tokens."""
    with patch.object(token_manager.encryption, "decrypt_token") as mock_decrypt:
        mock_decrypt.return_value = "decrypted_token"

        with patch.object(token_manager, "verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.side_effect = [
                (True, "Token verified"),  # test-agent-1
                (False, "Connection failed"),  # test-agent-3 (would be called for valid tokens)
            ]

            results = await token_manager.validate_all_tokens()

            assert len(results) == 3

            # Agent 1: Valid and authenticated
            assert results["test-agent-1"].status == TokenStatus.VALID
            assert results["test-agent-1"].auth_tested is True
            assert results["test-agent-1"].auth_successful is True

            # Agent 2: Missing token (not tested)
            assert results["test-agent-2"].status == TokenStatus.MISSING
            assert results["test-agent-2"].auth_tested is False

            # Agent 3: Unencrypted (not tested)
            assert results["test-agent-3"].status == TokenStatus.UNENCRYPTED
            assert results["test-agent-3"].auth_tested is False


@pytest.mark.asyncio
async def test_rotate_all_tokens_immediate(token_manager, mock_registry):
    """Test rotating all tokens with immediate strategy."""
    with patch.object(token_manager, "regenerate_token", new_callable=AsyncMock) as mock_regen:
        mock_regen.side_effect = [
            TokenRotationResult("test-agent-1", True, True, True, True, True),
            TokenRotationResult("test-agent-2", True, True, True, True, True),
            TokenRotationResult(
                "test-agent-3", False, True, True, False, False, "Failed to restart"
            ),
        ]

        results = await token_manager.rotate_all_tokens(strategy="immediate")

        assert len(results) == 3
        assert results["test-agent-1"].success is True
        assert results["test-agent-2"].success is True
        assert results["test-agent-3"].success is False

        # All agents should be rotated with immediate strategy
        assert mock_regen.call_count == 3


@pytest.mark.asyncio
async def test_rotate_all_tokens_canary(token_manager, mock_registry):
    """Test rotating tokens with canary strategy."""
    with patch.object(token_manager, "regenerate_token", new_callable=AsyncMock) as mock_regen:
        mock_regen.side_effect = [
            TokenRotationResult("test-agent-1", True, True, True, True, True),
            TokenRotationResult("test-agent-2", True, True, True, True, True),
            TokenRotationResult("test-agent-3", True, True, True, True, True),
        ]

        with patch.object(token_manager, "verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = (True, "Token verified")

            results = await token_manager.rotate_all_tokens(
                strategy="canary",
                canary_percentage=34,  # Should select 1 out of 3
            )

            assert len(results) == 3
            # With 34% of 3 agents, we should rotate 1 canary + 2 remaining = 3 total
            assert all(r.success for r in results.values())


def test_backup_metadata(token_manager, tmp_path):
    """Test backing up metadata."""
    # Create a mock metadata file
    metadata_file = tmp_path / "agents" / "metadata.json"
    metadata_file.write_text(json.dumps({"agents": {}}))

    backup_path = token_manager.backup_metadata()

    assert backup_path.exists()
    assert backup_path.parent == token_manager.backup_dir
    assert "metadata_backup" in backup_path.name

    # Check content matches
    with open(backup_path) as f:
        backup_data = json.load(f)
    assert backup_data == {"agents": {}}


def test_restore_metadata(token_manager, mock_registry, tmp_path):
    """Test restoring metadata from backup."""
    # Create backup file
    backup_data = {"agents": {"test": {"name": "Test"}}}
    backup_file = tmp_path / "backup.json"
    backup_file.write_text(json.dumps(backup_data))

    # Create target metadata file
    metadata_file = tmp_path / "agents" / "metadata.json"
    metadata_file.write_text(json.dumps({"agents": {}}))

    mock_registry._load_metadata = Mock()

    success = token_manager.restore_metadata(backup_file)

    assert success is True

    # Check metadata was restored
    with open(metadata_file) as f:
        restored_data = json.load(f)
    assert restored_data == backup_data

    # Check registry was reloaded
    mock_registry._load_metadata.assert_called_once()
