"""
Tests for auth configuration loading.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from pydantic import ValidationError

from ciris_manager.api.auth import load_oauth_config
from ciris_manager.config.settings import AuthConfig, CIRISManagerConfig


class TestAuthConfig:
    """Test auth configuration loading."""

    def test_load_oauth_config_from_file(self):
        """Test loading OAuth config from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config file
            config_dir = Path(tmpdir) / "shared/oauth"
            config_dir.mkdir(parents=True)
            config_file = config_dir / "google_oauth_manager.json"

            config_data = {"client_id": "file-client-id", "client_secret": "file-client-secret"}
            config_file.write_text(json.dumps(config_data))

            # Mock home directory
            with patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with patch("ciris_manager.api.auth.init_auth_service") as mock_init:
                    result = load_oauth_config()

                    assert result is True
                    mock_init.assert_called_once_with(
                        google_client_id="file-client-id", google_client_secret="file-client-secret"
                    )

    def test_load_oauth_config_file_error(self):
        """Test loading OAuth config with file error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create invalid config file
            config_dir = Path(tmpdir) / "shared/oauth"
            config_dir.mkdir(parents=True)
            config_file = config_dir / "google_oauth_manager.json"
            config_file.write_text("invalid json")

            with patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with patch("ciris_manager.api.auth.init_auth_service") as mock_init:
                    result = load_oauth_config()

                    # Should fall back to env vars
                    assert result is False
                    mock_init.assert_not_called()

    def test_load_oauth_config_from_env(self):
        """Test loading OAuth config from environment variables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No config file
            with patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with patch.dict(
                    "os.environ",
                    {
                        "GOOGLE_CLIENT_ID": "env-client-id",
                        "GOOGLE_CLIENT_SECRET": "env-client-secret",
                    },
                ):
                    with patch("ciris_manager.api.auth.init_auth_service") as mock_init:
                        result = load_oauth_config()

                        assert result is True
                        mock_init.assert_called_once_with(
                            google_client_id="env-client-id",
                            google_client_secret="env-client-secret",
                        )

    def test_load_oauth_config_no_credentials(self):
        """Test loading OAuth config without any credentials."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No config file and no env vars
            with patch("pathlib.Path.home", return_value=Path(tmpdir)):
                with patch.dict("os.environ", {}, clear=True):
                    with patch("ciris_manager.api.auth.init_auth_service") as mock_init:
                        result = load_oauth_config()

                        assert result is False
                        mock_init.assert_not_called()

    def test_load_oauth_config_partial_env(self):
        """Test loading OAuth config with partial environment variables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("pathlib.Path.home", return_value=Path(tmpdir)):
                # Only client ID, no secret
                with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "env-client-id"}):
                    with patch("ciris_manager.api.auth.init_auth_service") as mock_init:
                        result = load_oauth_config()

                        assert result is False
                        mock_init.assert_not_called()


class TestAuthConfigMode:
    """Test auth mode configuration."""

    def test_auth_mode_defaults_to_production(self):
        """Test that auth mode defaults to production for security."""
        config = AuthConfig()
        assert config.mode == "production"

    def test_auth_mode_accepts_development(self):
        """Test that auth mode can be set to development."""
        config = AuthConfig(mode="development")
        assert config.mode == "development"

    def test_auth_mode_accepts_production(self):
        """Test that auth mode can be set to production."""
        config = AuthConfig(mode="production")
        assert config.mode == "production"

    def test_auth_mode_rejects_invalid_values(self):
        """Test that auth mode rejects invalid values."""
        with pytest.raises(ValidationError) as exc_info:
            AuthConfig(mode="invalid")

        # Check the error message contains information about valid values
        error_str = str(exc_info.value)
        assert "development" in error_str or "production" in error_str

    def test_ciris_manager_config_includes_auth(self):
        """Test that CIRISManagerConfig includes auth configuration."""
        config = CIRISManagerConfig()
        assert hasattr(config, "auth")
        assert isinstance(config.auth, AuthConfig)
        assert config.auth.mode == "production"  # Default

    def test_auth_config_from_dict(self):
        """Test creating auth config from dictionary."""
        config_dict = {"mode": "development"}
        config = AuthConfig(**config_dict)
        assert config.mode == "development"

    def test_full_config_with_auth_mode(self):
        """Test full config can be created with auth mode."""
        config = CIRISManagerConfig(auth={"mode": "development"})
        assert config.auth.mode == "development"
