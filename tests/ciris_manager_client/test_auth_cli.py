"""
Unit tests for CLI authentication functionality.

Tests the auth command and token loading in ciris_manager_client.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from ciris_manager.auth_cli import AuthManager, handle_auth_command
from ciris_manager_client.main import (
    load_token,
    create_parser,
    EXIT_SUCCESS,
    EXIT_INVALID_ARGS,
)


class TestLoadToken:
    """Tests for load_token function."""

    def test_load_token_from_env_var(self, monkeypatch):
        """Test that environment variable takes priority."""
        monkeypatch.setenv("CIRIS_MANAGER_TOKEN", "env-token-123")
        assert load_token() == "env-token-123"

    def test_load_token_from_device_flow_file(self, tmp_path, monkeypatch):
        """Test loading token from device flow JSON file."""
        # Clear env var
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        # Create device flow token file
        config_dir = tmp_path / ".config" / "ciris-manager"
        config_dir.mkdir(parents=True)
        token_file = config_dir / "token.json"

        # Token expires in 1 hour
        expires_at = datetime.utcnow() + timedelta(hours=1)
        token_data = {
            "token": "device-flow-token-456",
            "email": "test@ciris.ai",
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.utcnow().isoformat(),
        }
        token_file.write_text(json.dumps(token_data))

        # Mock Path.home() to return tmp_path
        with patch.object(Path, "home", return_value=tmp_path):
            result = load_token()
            assert result == "device-flow-token-456"

    def test_load_token_expired_device_flow(self, tmp_path, monkeypatch):
        """Test that expired device flow token is not returned."""
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        # Create expired token file
        config_dir = tmp_path / ".config" / "ciris-manager"
        config_dir.mkdir(parents=True)
        token_file = config_dir / "token.json"

        expires_at = datetime.utcnow() - timedelta(hours=1)  # Expired
        token_data = {
            "token": "expired-token",
            "email": "test@ciris.ai",
            "expires_at": expires_at.isoformat(),
        }
        token_file.write_text(json.dumps(token_data))

        with patch.object(Path, "home", return_value=tmp_path):
            result = load_token()
            # Should not return expired token
            assert result is None

    def test_load_token_from_legacy_file(self, tmp_path, monkeypatch):
        """Test loading token from legacy .manager_token file."""
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        # Create legacy token file
        legacy_file = tmp_path / ".manager_token"
        legacy_file.write_text("legacy-token-789\n")

        with patch.object(Path, "home", return_value=tmp_path):
            result = load_token()
            assert result == "legacy-token-789"

    def test_load_token_device_flow_priority_over_legacy(self, tmp_path, monkeypatch):
        """Test that device flow token takes priority over legacy file."""
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        # Create both files
        config_dir = tmp_path / ".config" / "ciris-manager"
        config_dir.mkdir(parents=True)
        device_token_file = config_dir / "token.json"

        expires_at = datetime.utcnow() + timedelta(hours=1)
        device_token_data = {
            "token": "device-flow-token",
            "email": "test@ciris.ai",
            "expires_at": expires_at.isoformat(),
        }
        device_token_file.write_text(json.dumps(device_token_data))

        legacy_file = tmp_path / ".manager_token"
        legacy_file.write_text("legacy-token")

        with patch.object(Path, "home", return_value=tmp_path):
            result = load_token()
            assert result == "device-flow-token"

    def test_load_token_no_token_found(self, tmp_path, monkeypatch):
        """Test that None is returned when no token is found."""
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        with patch.object(Path, "home", return_value=tmp_path):
            result = load_token()
            assert result is None

    def test_load_token_invalid_json(self, tmp_path, monkeypatch):
        """Test handling of invalid JSON in device flow file."""
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        config_dir = tmp_path / ".config" / "ciris-manager"
        config_dir.mkdir(parents=True)
        token_file = config_dir / "token.json"
        token_file.write_text("invalid json {")

        with patch.object(Path, "home", return_value=tmp_path):
            result = load_token()
            assert result is None


class TestSetupAuthParser:
    """Tests for setup_auth_parser function."""

    def test_auth_parser_created(self):
        """Test that auth parser is properly configured."""
        parser = create_parser()
        # --help causes SystemExit(0), which is expected
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["auth", "--help"])
        assert exc_info.value.code == 0

    def test_auth_login_subcommand(self):
        """Test auth login subcommand parsing."""
        parser = create_parser()
        args = parser.parse_args(["auth", "login", "test@ciris.ai"])
        assert args.command == "auth"
        assert args.auth_command == "login"
        assert args.email == "test@ciris.ai"

    def test_auth_login_without_email(self):
        """Test auth login subcommand without email."""
        parser = create_parser()
        args = parser.parse_args(["auth", "login"])
        assert args.command == "auth"
        assert args.auth_command == "login"
        assert args.email is None

    def test_auth_logout_subcommand(self):
        """Test auth logout subcommand parsing."""
        parser = create_parser()
        args = parser.parse_args(["auth", "logout"])
        assert args.command == "auth"
        assert args.auth_command == "logout"

    def test_auth_status_subcommand(self):
        """Test auth status subcommand parsing."""
        parser = create_parser()
        args = parser.parse_args(["auth", "status"])
        assert args.command == "auth"
        assert args.auth_command == "status"

    def test_auth_token_subcommand(self):
        """Test auth token subcommand parsing."""
        parser = create_parser()
        args = parser.parse_args(["auth", "token"])
        assert args.command == "auth"
        assert args.auth_command == "token"


class TestAuthManager:
    """Tests for AuthManager class."""

    def test_init(self, tmp_path):
        """Test AuthManager initialization."""
        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager(base_url="https://test.ciris.ai")
            assert manager.base_url == "https://test.ciris.ai"
            assert manager.config_dir == tmp_path / ".config" / "ciris-manager"
            assert manager.token_file == tmp_path / ".config" / "ciris-manager" / "token.json"

    def test_save_and_load_token(self, tmp_path):
        """Test saving and loading a token."""
        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            manager.save_token("test-token-abc", "user@ciris.ai")

            # Verify file permissions
            assert (manager.token_file.stat().st_mode & 0o777) == 0o600

            # Load token
            token_data = manager.load_token()
            assert token_data is not None
            assert token_data["token"] == "test-token-abc"
            assert token_data["email"] == "user@ciris.ai"

    def test_load_expired_token(self, tmp_path):
        """Test that expired tokens are not loaded."""
        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()

            # Create expired token
            config_dir = tmp_path / ".config" / "ciris-manager"
            config_dir.mkdir(parents=True, exist_ok=True)
            token_file = config_dir / "token.json"

            expired = datetime.utcnow() - timedelta(hours=1)
            token_data = {
                "token": "expired-token",
                "email": "test@ciris.ai",
                "expires_at": expired.isoformat(),
            }
            token_file.write_text(json.dumps(token_data))

            result = manager.load_token()
            assert result is None
            # Token file should be deleted
            assert not token_file.exists()

    def test_logout_removes_token(self, tmp_path, capsys):
        """Test that logout removes the token file."""
        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            manager.save_token("test-token", "user@ciris.ai")
            assert manager.token_file.exists()

            manager.logout()
            assert not manager.token_file.exists()

            captured = capsys.readouterr()
            assert "Logged out successfully" in captured.out

    def test_logout_when_not_logged_in(self, tmp_path, capsys):
        """Test logout when not logged in."""
        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            manager.logout()

            captured = capsys.readouterr()
            assert "Not logged in" in captured.out

    @patch("ciris_manager.auth_cli.requests.get")
    def test_test_token_valid(self, mock_get, tmp_path):
        """Test token validation with valid token."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            result = manager.test_token("valid-token")
            assert result is True

            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "Authorization" in call_args[1]["headers"]
            assert call_args[1]["headers"]["Authorization"] == "Bearer valid-token"

    @patch("ciris_manager.auth_cli.requests.get")
    def test_test_token_invalid(self, mock_get, tmp_path):
        """Test token validation with invalid token."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            result = manager.test_token("invalid-token")
            assert result is False

    @patch("ciris_manager.auth_cli.requests.post")
    def test_request_device_code_success(self, mock_post, tmp_path):
        """Test successful device code request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "device_code": "dev-code-123",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://agents.ciris.ai/manager/v1/device",
            "interval": 5,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            result = manager.request_device_code()

            assert result["device_code"] == "dev-code-123"
            assert result["user_code"] == "ABCD-EFGH"

    @patch("ciris_manager.auth_cli.requests.post")
    def test_poll_for_token_success(self, mock_post, tmp_path):
        """Test successful token polling."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "new-access-token-xyz"}
        mock_post.return_value = mock_response

        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            result = manager.poll_for_token("device-code-123", interval=1, timeout=5)

            assert result == "new-access-token-xyz"

    @patch("ciris_manager.auth_cli.requests.post")
    def test_poll_for_token_pending(self, mock_post, tmp_path):
        """Test token polling with pending status."""
        # First call returns pending, second returns success
        pending_response = Mock()
        pending_response.status_code = 400
        pending_response.json.return_value = {"error": "authorization_pending"}

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"access_token": "success-token"}

        mock_post.side_effect = [pending_response, success_response]

        with patch.object(Path, "home", return_value=tmp_path):
            manager = AuthManager()
            result = manager.poll_for_token("device-code-123", interval=0.1, timeout=5)

            assert result == "success-token"


class TestHandleAuthCommand:
    """Tests for handle_auth_command function."""

    def test_login_requires_email(self, tmp_path, capsys):
        """Test that login requires an email address."""
        import argparse

        with patch.object(Path, "home", return_value=tmp_path):
            args = argparse.Namespace(
                base_url="https://agents.ciris.ai",
                auth_command="login",
                email=None,
            )
            result = handle_auth_command(args)
            assert result == 1

            captured = capsys.readouterr()
            assert "Email required" in captured.out

    def test_login_requires_ciris_email(self, tmp_path, capsys):
        """Test that login requires @ciris.ai email."""
        import argparse

        with patch.object(Path, "home", return_value=tmp_path):
            args = argparse.Namespace(
                base_url="https://agents.ciris.ai",
                auth_command="login",
                email="user@gmail.com",
            )
            result = handle_auth_command(args)
            assert result == 1

            captured = capsys.readouterr()
            assert "@ciris.ai email addresses are allowed" in captured.out

    def test_logout_command(self, tmp_path, capsys):
        """Test logout command."""
        import argparse

        with patch.object(Path, "home", return_value=tmp_path):
            args = argparse.Namespace(
                base_url="https://agents.ciris.ai",
                auth_command="logout",
            )
            result = handle_auth_command(args)
            assert result == 0

    def test_status_not_authenticated(self, tmp_path, capsys):
        """Test status command when not authenticated."""
        import argparse

        with patch.object(Path, "home", return_value=tmp_path):
            args = argparse.Namespace(
                base_url="https://agents.ciris.ai",
                auth_command="status",
            )
            result = handle_auth_command(args)
            assert result == 0

            captured = capsys.readouterr()
            assert "Not authenticated" in captured.out

    def test_token_not_authenticated(self, tmp_path, capsys):
        """Test token command when not authenticated."""
        import argparse

        with patch.object(Path, "home", return_value=tmp_path):
            args = argparse.Namespace(
                base_url="https://agents.ciris.ai",
                auth_command="token",
            )
            result = handle_auth_command(args)
            assert result == 1

            captured = capsys.readouterr()
            assert "Not authenticated" in captured.err

    def test_unknown_auth_command(self, tmp_path, capsys):
        """Test handling of unknown auth command."""
        import argparse

        with patch.object(Path, "home", return_value=tmp_path):
            args = argparse.Namespace(
                base_url="https://agents.ciris.ai",
                auth_command="unknown",
            )
            result = handle_auth_command(args)
            assert result == 1

            captured = capsys.readouterr()
            assert "Unknown auth command" in captured.out


class TestCLIIntegration:
    """Integration tests for CLI auth workflow."""

    def test_main_auth_no_subcommand(self, monkeypatch, capsys):
        """Test main() with auth command but no subcommand."""
        from ciris_manager_client.main import main

        monkeypatch.setattr(sys, "argv", ["ciris-manager-client", "auth"])
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        result = main()
        assert result == EXIT_INVALID_ARGS

        captured = capsys.readouterr()
        assert "No auth subcommand specified" in captured.err

    def test_main_no_token_no_auth(self, monkeypatch, tmp_path, capsys):
        """Test main() with non-auth command and no token."""
        from ciris_manager_client.main import main

        monkeypatch.setattr(sys, "argv", ["ciris-manager-client", "deployment", "status"])
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        with patch.object(Path, "home", return_value=tmp_path):
            result = main()

        # Should fail due to no token
        assert result != EXIT_SUCCESS

        captured = capsys.readouterr()
        assert "No authentication token found" in captured.err or "auth login" in captured.err

    def test_main_auth_status_works_without_token(self, monkeypatch, tmp_path, capsys):
        """Test that auth status works even without a saved token."""
        from ciris_manager_client.main import main

        monkeypatch.setattr(sys, "argv", ["ciris-manager-client", "auth", "status"])
        monkeypatch.delenv("CIRIS_MANAGER_TOKEN", raising=False)

        with patch.object(Path, "home", return_value=tmp_path):
            result = main()

        # Should succeed (shows "not authenticated" status)
        assert result == EXIT_SUCCESS

        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out
