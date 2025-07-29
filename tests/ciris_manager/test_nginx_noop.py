"""Tests for NoOpNginxManager."""

import pytest
import logging
from ciris_manager.nginx_noop import NoOpNginxManager


class TestNoOpNginxManager:
    """Test the no-op nginx manager implementation."""

    def test_init_logs_disabled_message(self, caplog):
        """Test that initialization logs the disabled message."""
        with caplog.at_level(logging.INFO):
            NoOpNginxManager()

        assert "Nginx integration is disabled" in caplog.text
        assert "Using No-Op Nginx Manager" in caplog.text

    def test_update_config_returns_true(self, caplog):
        """Test that update_config always returns True."""
        manager = NoOpNginxManager()
        agents = [
            {"agent_id": "test-1", "port": 8080},
            {"agent_id": "test-2", "port": 8081},
        ]

        with caplog.at_level(logging.DEBUG):
            result = manager.update_config(agents)

        assert result is True
        assert "skipping configuration update for 2 agents" in caplog.text

    @pytest.mark.asyncio
    async def test_update_nginx_config_async_returns_true(self, caplog):
        """Test that async update_nginx_config returns True."""
        manager = NoOpNginxManager()

        with caplog.at_level(logging.DEBUG):
            result = await manager.update_nginx_config()

        assert result is True
        assert "skipping async configuration update" in caplog.text

    def test_remove_agent_routes_returns_true(self, caplog):
        """Test that remove_agent_routes always returns True."""
        manager = NoOpNginxManager()
        agents = [{"agent_id": "remaining", "port": 8080}]

        with caplog.at_level(logging.DEBUG):
            result = manager.remove_agent_routes("test-agent", agents)

        assert result is True
        assert "skipping route removal for agent test-agent" in caplog.text

    def test_reload_returns_true(self, caplog):
        """Test that reload always returns True."""
        manager = NoOpNginxManager()

        with caplog.at_level(logging.DEBUG):
            result = manager.reload()

        assert result is True
        assert "skipping reload" in caplog.text

    def test_init_with_params_ignored(self):
        """Test that init parameters are ignored."""
        manager = NoOpNginxManager(config_dir="/etc/nginx", container_name="nginx-proxy")

        # Should initialize without error
        assert isinstance(manager, NoOpNginxManager)

    def test_empty_agents_list(self):
        """Test handling of empty agents list."""
        manager = NoOpNginxManager()
        result = manager.update_config([])

        assert result is True

    def test_none_agents_list(self):
        """Test handling of None agents list."""
        manager = NoOpNginxManager()
        # This might raise an error in real implementation
        # but NoOp should handle gracefully
        try:
            result = manager.update_config(None)
            assert result is True
        except TypeError:
            # If it does raise, that's also acceptable
            pass
