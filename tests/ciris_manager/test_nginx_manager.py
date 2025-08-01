"""
Tests for nginx configuration management.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile

from ciris_manager.nginx_manager import NginxManager


class TestNginxManager:
    """Test nginx configuration management."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for nginx configs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def nginx_manager(self, temp_dir):
        """Create nginx manager with temp directory."""
        return NginxManager(config_dir=str(temp_dir), container_name="test-nginx")

    @pytest.fixture
    def sample_agents(self):
        """Sample agent data."""
        from ciris_manager.models import AgentInfo
        
        return [
            AgentInfo(
                agent_id="agent-scout",
                agent_name="Scout",
                container_name="ciris-agent-scout",
                api_port=8081,
                status="running",
            ),
            AgentInfo(
                agent_id="agent-sage",
                agent_name="Sage",
                container_name="ciris-agent-sage",
                api_port=8082,
                status="running",
            ),
        ]

    def test_init(self, nginx_manager, temp_dir):
        """Test initialization."""
        assert nginx_manager.config_dir == temp_dir
        assert nginx_manager.container_name == "test-nginx"
        assert nginx_manager.config_path == temp_dir / "nginx.conf"
        assert nginx_manager.new_config_path == temp_dir / "nginx.conf.new"
        assert nginx_manager.backup_path == temp_dir / "nginx.conf.backup"

    def test_generate_config(self, nginx_manager, sample_agents):
        """Test config generation."""
        config = nginx_manager.generate_config(sample_agents)

        # Check basic structure
        assert "events {" in config
        assert "http {" in config
        assert "server {" in config

        # Check upstreams
        assert "upstream agent_gui {" in config
        assert "server 127.0.0.1:3000;" in config
        assert "upstream manager {" in config
        assert "server 127.0.0.1:8888;" in config

        # Check agent routes
        assert "location ~ ^/api/agent-scout/" in config
        assert "proxy_pass http://agent_agent-scout/" in config
        assert "location ~ ^/api/agent-sage/" in config
        assert "proxy_pass http://agent_agent-sage/" in config

    @patch("subprocess.run")
    def test_validate_config_success(self, mock_run, nginx_manager):
        """Test config validation success."""
        # Create a test config file
        nginx_manager.new_config_path.write_text("valid config")

        # Mock successful validation
        mock_run.return_value = MagicMock(returncode=0)

        result = nginx_manager._validate_config()
        assert result is True

        # Should have called docker exec nginx -t
        assert mock_run.call_count == 1

        # Check the nginx -t command
        nginx_call = mock_run.call_args_list[0]
        assert nginx_call[0][0][0] == "docker"
        assert nginx_call[0][0][1] == "exec"
        assert nginx_call[0][0][2] == "test-nginx"
        assert nginx_call[0][0][3] == "nginx"
        assert nginx_call[0][0][4] == "-t"

    @patch("subprocess.run")
    def test_validate_config_failure(self, mock_run, nginx_manager):
        """Test config validation failure."""
        # Create a test config file
        nginx_manager.new_config_path.write_text("invalid config")

        # Mock failed validation (no docker cp needed with volume mounts)
        mock_run.return_value = MagicMock(
            returncode=1, stderr=b"nginx: configuration file test failed"
        )

        result = nginx_manager._validate_config()
        assert result is False

    @patch("subprocess.run")
    def test_reload_nginx_success(self, mock_run, nginx_manager):
        """Test nginx reload success."""
        mock_run.return_value = MagicMock(returncode=0)

        result = nginx_manager._reload_nginx()
        assert result is True

        # Should have called nginx reload
        assert mock_run.call_count == 1

        # Check the reload command
        reload_call = mock_run.call_args_list[0]
        assert reload_call[0][0][0] == "docker"
        assert reload_call[0][0][1] == "exec"
        assert reload_call[0][0][2] == "test-nginx"
        assert reload_call[0][0][3] == "nginx"
        assert reload_call[0][0][4] == "-s"
        assert reload_call[0][0][5] == "reload"

    @patch("subprocess.run")
    def test_update_config_success(self, mock_run, nginx_manager, sample_agents):
        """Test successful config update."""
        # Mock successful validation and reload
        mock_run.return_value = MagicMock(returncode=0)

        result = nginx_manager.update_config(sample_agents)
        assert result is True

        # Should have called: nginx -t, nginx -s reload
        assert mock_run.call_count == 2

        # Check that config files were created
        assert nginx_manager.config_path.exists()
        assert not nginx_manager.new_config_path.exists()  # Should be cleaned up

    @patch("subprocess.run")
    def test_update_config_validation_failure(self, mock_run, nginx_manager, sample_agents):
        """Test config update with validation failure."""
        # nginx -t fails (no docker cp needed)
        mock_run.return_value = MagicMock(returncode=1, stderr=b"Invalid config")

        result = nginx_manager.update_config(sample_agents)
        assert result is False

        # Should call nginx -t, but not reload
        assert mock_run.call_count == 1

        # Original config should be unchanged if it existed
        if nginx_manager.config_path.exists():
            # Would check content is unchanged
            pass

    @patch("subprocess.run")
    def test_rollback(self, mock_run, nginx_manager):
        """Test rollback functionality."""
        # Mock successful reload
        mock_run.return_value = MagicMock(returncode=0)

        # Create original and backup configs
        nginx_manager.config_path.write_text("original config")
        nginx_manager.backup_path.write_text("backup config")

        # Do rollback
        nginx_manager._rollback()

        # Check that backup was restored
        assert nginx_manager.config_path.read_text() == "backup config"
        # Backup file should still exist (not deleted by rollback)
        assert nginx_manager.backup_path.exists()

    @patch("subprocess.run")
    def test_remove_agent_routes(self, mock_run, nginx_manager, sample_agents):
        """Test removing agent routes."""
        # Mock successful operations
        mock_run.return_value = MagicMock(returncode=0)

        # Remove one agent
        remaining_agents = [a for a in sample_agents if a.agent_id != "agent-scout"]
        result = nginx_manager.remove_agent_routes("agent-scout", remaining_agents)

        assert result is True

        # Should have made 2 calls: nginx -t, nginx -s reload (no docker cp needed)
        assert mock_run.call_count == 2

        # Check that new config only has remaining agent
        config = nginx_manager.config_path.read_text()
        assert "agent-sage" in config
        assert "agent-scout" not in config

    def test_get_current_config(self, nginx_manager):
        """Test getting current config."""
        # No config exists
        config = nginx_manager.get_current_config()
        assert config is None

        # Create config
        nginx_manager.config_path.write_text("test config content")
        config = nginx_manager.get_current_config()
        assert config == "test config content"

    def test_empty_agents_config(self, nginx_manager):
        """Test config generation with no agents."""
        config = nginx_manager.generate_config([])

        # Should still have basic structure
        assert "events {" in config
        assert "http {" in config
        assert "server {" in config

        # Should have GUI and manager upstreams
        assert "upstream agent_gui {" in config
        assert "upstream manager {" in config

        # But no agent-specific routes
        assert "/api/agent-" not in config
