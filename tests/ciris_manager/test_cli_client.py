"""Tests for CLI client commands."""

import json
import math
from unittest.mock import Mock, patch
import argparse

from ciris_manager.cli_client import (
    handle_agent_commands,
    handle_system_commands,
    print_json,
    print_table,
)


class TestCLIOutput:
    """Test CLI output formatting functions."""

    def test_print_json(self, capsys):
        """Test JSON output formatting."""
        data = {"test": "value", "number": 42}
        print_json(data)
        captured = capsys.readouterr()
        assert json.loads(captured.out) == data

    def test_print_table(self, capsys):
        """Test table output formatting."""
        rows = [["test1", "value1"], ["test2", "value2"]]
        headers = ["Name", "Value"]
        print_table(rows, headers)
        captured = capsys.readouterr()
        # Check headers are present
        assert "Name" in captured.out
        assert "Value" in captured.out
        # Check data is present
        assert "test1" in captured.out
        assert "value1" in captured.out


class TestAgentCommands:
    """Test agent management CLI commands."""

    def test_agent_list(self, capsys):
        """Test agent list command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_agents.return_value = [
            {
                "agent_id": "test-123",
                "agent_name": "Test Agent",
                "status": "running",
                "api_port": 8080,
                "container_name": "ciris-test-123",
            }
        ]

        # Setup args
        args = argparse.Namespace(agent_command="list", json=False)

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "test-123" in captured.out
        assert "Test Agent" in captured.out
        mock_client.list_agents.assert_called_once()

    def test_agent_list_json(self, capsys):
        """Test agent list command with JSON output."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_agents.return_value = [
            {
                "agent_id": "test-123",
                "agent_name": "Test Agent",
                "status": "running",
            }
        ]

        # Setup args
        args = argparse.Namespace(agent_command="list", json=True)

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data[0]["agent_id"] == "test-123"

    def test_agent_get(self, capsys):
        """Test agent get command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.get_agent.return_value = {
            "agent_id": "test-123",
            "agent_name": "Test Agent",
            "status": "running",
        }

        # Setup args
        args = argparse.Namespace(agent_command="get", agent_id="test-123")

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["agent_id"] == "test-123"
        mock_client.get_agent.assert_called_once_with("test-123")

    def test_agent_create(self, capsys):
        """Test agent create command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.create_agent.return_value = {
            "agent_id": "test-123",
            "status": "created",
        }

        # Setup args - provide required name and template
        args = argparse.Namespace(
            agent_command="create",
            template="scout",
            name="Test Agent",
            mock_llm=True,
            discord=False,
            env=[],
            json=False,
        )

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "test-123" in captured.out or "created" in captured.out

    def test_agent_create_with_args(self, capsys):
        """Test agent create command with arguments."""
        # Setup mock client
        mock_client = Mock()
        mock_client.create_agent.return_value = {
            "agent_id": "test-123",
            "status": "created",
        }

        # Setup args
        args = argparse.Namespace(
            agent_command="create",
            template="scout",
            name="Test Agent",
            mock_llm=True,
            discord=False,
            env=["KEY1=value1", "KEY2=value2"],
            json=False,  # Add missing json attribute
        )

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        mock_client.create_agent.assert_called_once_with(
            name="Test Agent",
            template="scout",
            environment={"KEY1": "value1", "KEY2": "value2"},
            mounts=None,
            use_mock_llm=True,
            enable_discord=False,
        )

    @patch("builtins.input")
    def test_agent_delete(self, mock_input, capsys):
        """Test agent delete command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.delete_agent.return_value = {"status": "deleted"}

        # Mock confirmation
        mock_input.return_value = "y"

        # Setup args with yes=False to trigger confirmation prompt
        args = argparse.Namespace(
            agent_command="delete", agent_id="test-123", yes=False, json=False
        )

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "deleted" in captured.out.lower()
        mock_client.delete_agent.assert_called_once_with("test-123")

    def test_agent_restart(self, capsys):
        """Test agent restart command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.restart_agent.return_value = {"status": "restarted"}

        # Setup args
        args = argparse.Namespace(agent_command="restart", agent_id="test-123", json=False)

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "restart" in captured.out.lower()
        mock_client.restart_agent.assert_called_once_with("test-123")

    def test_agent_logs(self, capsys):
        """Test agent logs command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.get_agent_logs.return_value = {"logs": "Test log output\nAnother line"}

        # Setup args
        args = argparse.Namespace(agent_command="logs", agent_id="test-123", lines=50)

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "Test log output" in captured.out
        mock_client.get_agent_logs.assert_called_once_with("test-123", lines=50)

    def test_agent_config_update(self, capsys):
        """Test agent config update command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.update_agent_config.return_value = {"status": "updated"}

        # Setup args - the refactored code uses "update" command directly
        args = argparse.Namespace(
            agent_command="update",
            agent_id="test-123",
            disable_mock_llm=True,
            enable_production=False,
            json=False,
        )

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "updated" in captured.out.lower()

    def test_agent_start(self, capsys):
        """Test agent start command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.start_agent.return_value = {"status": "started"}

        # Setup args
        args = argparse.Namespace(agent_command="start", agent_id="test-123", json=False)

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "start" in captured.out.lower()

    def test_agent_stop(self, capsys):
        """Test agent stop command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.stop_agent.return_value = {"status": "stopped"}

        # Setup args
        args = argparse.Namespace(agent_command="stop", agent_id="test-123", json=False)

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "stop" in captured.out.lower()


class TestSystemCommands:
    """Test system management CLI commands."""

    def test_system_status(self, capsys):
        """Test system status command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.get_status.return_value = {
            "status": "running",
            "agents": 5,
            "version": "1.0.0",
        }

        # Setup args
        args = argparse.Namespace(system_command="status")

        # Run command
        result = handle_system_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "running"
        mock_client.get_status.assert_called_once()

    def test_system_health(self, capsys):
        """Test system health command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.get_health.return_value = {"status": "healthy"}

        # Setup args
        args = argparse.Namespace(system_command="health")

        # Run command
        result = handle_system_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "healthy"
        mock_client.get_health.assert_called_once()

    def test_system_metrics(self, capsys):
        """Test system metrics command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.get_metrics.return_value = {
            "cpu_usage": 45.2,
            "memory_usage": 1024,
            "disk_usage": 50.0,
        }

        # Setup args
        args = argparse.Namespace(system_command="metrics")

        # Run command
        result = handle_system_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert math.isclose(data["cpu_usage"], 45.2, rel_tol=1e-9)
        mock_client.get_metrics.assert_called_once()

    def test_system_update_status(self, capsys):
        """Test system update status command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.get_update_status.return_value = {
            "deployment_id": "dep-123",
            "status": "in_progress",
            "phase": "canary",
        }

        # Setup args
        args = argparse.Namespace(system_command="update-status")

        # Run command
        result = handle_system_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "in_progress"
        mock_client.get_update_status.assert_called_once()

    @patch("builtins.input")
    def test_system_notify_update(self, mock_input, capsys):
        """Test system update notification."""
        # Setup mock client
        mock_client = Mock()
        mock_client.notify_update.return_value = {
            "deployment_id": "dep-123",
            "status": "started",
        }

        # Mock confirmation
        mock_input.return_value = "y"

        # Setup args with yes=False to trigger confirmation
        args = argparse.Namespace(
            system_command="notify-update",
            agent_image="agent:latest",
            gui_image="gui:latest",
            strategy="canary",
            message=None,
            yes=False,
            json=False,
        )

        # Run command
        result = handle_system_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "dep-123" in captured.out or "started" in captured.out
        mock_client.notify_update.assert_called_once()

    def test_system_templates(self, capsys):
        """Test system templates command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.list_templates.return_value = [
            {"name": "scout", "description": "Scout template"},
            {"name": "sage", "description": "Sage template"},
        ]

        # Setup args
        args = argparse.Namespace(system_command="templates")

        # Run command
        result = handle_system_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "scout" in captured.out
        assert "sage" in captured.out

    def test_system_ping(self, capsys):
        """Test system ping command."""
        # Setup mock client
        mock_client = Mock()
        mock_client.ping.return_value = {"status": "pong"}

        # Setup args
        args = argparse.Namespace(system_command="ping")

        # Run command
        result = handle_system_commands(mock_client, args)

        # Verify
        assert result == 0
        captured = capsys.readouterr()
        assert "pong" in captured.out


class TestCLIErrorHandling:
    """Test CLI error handling."""

    def test_connection_error(self, capsys):
        """Test handling of connection errors."""
        from ciris_manager.sdk import CIRISManagerError

        # Setup mock client to raise exception
        mock_client = Mock()
        mock_client.list_agents.side_effect = CIRISManagerError("Connection refused")

        # Setup args
        args = argparse.Namespace(agent_command="list", json=False)

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify error handling
        assert result != 0
        captured = capsys.readouterr()
        assert "Connection refused" in captured.err  # Check stderr, not stdout

    def test_authentication_error(self, capsys):
        """Test handling of authentication errors."""
        from ciris_manager.sdk import AuthenticationError

        # Setup mock client to raise exception
        mock_client = Mock()
        mock_client.get_agent.side_effect = AuthenticationError("Invalid token")

        # Setup args
        args = argparse.Namespace(agent_command="get", agent_id="test-123")

        # Run command
        result = handle_agent_commands(mock_client, args)

        # Verify error handling
        assert result != 0
        captured = capsys.readouterr()
        assert "Invalid token" in captured.err or "Authentication" in captured.err  # Check stderr

    def test_invalid_command(self):
        """Test handling of invalid command."""
        # Setup mock client
        mock_client = Mock()

        # Setup args with invalid command
        args = argparse.Namespace(
            agent_command="invalid_command",
        )

        # Run command - should not crash
        result = handle_agent_commands(mock_client, args)

        # Should return non-zero for unknown command
        assert result != 0
