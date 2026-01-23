"""
Unit tests for compose_command utility module.
"""

import pytest
import subprocess
from unittest.mock import patch, MagicMock

import ciris_manager.utils.compose_command as compose_module
from ciris_manager.utils.compose_command import (
    get_compose_command,
    compose_cmd,
    reset_compose_command_cache,
)


class TestGetComposeCommand:
    """Tests for get_compose_command function."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset the compose command cache before each test."""
        reset_compose_command_cache()
        yield
        reset_compose_command_cache()

    def test_detects_compose_v2(self):
        """Test detection of Docker Compose v2 (docker compose)."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"Docker Compose version v2.20.0"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = get_compose_command()

            assert result == ["docker", "compose"]
            mock_run.assert_called_once_with(
                ["docker", "compose", "version"],
                capture_output=True,
                timeout=5,
            )

    def test_falls_back_to_compose_v1(self):
        """Test fallback to Docker Compose v1 when v2 not available."""
        mock_result = MagicMock()
        mock_result.returncode = 1  # v2 fails

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/docker-compose") as mock_which:
                result = get_compose_command()

                assert result == ["docker-compose"]
                mock_which.assert_called_once_with("docker-compose")

    def test_raises_when_neither_available(self):
        """Test ComposeNotFoundError raised when neither v1 nor v2 is available."""
        from ciris_manager.utils.compose_command import ComposeNotFoundError

        mock_result = MagicMock()
        mock_result.returncode = 1  # v2 fails
        mock_result.stderr = b"compose is not a docker command"

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value=None):  # v1 not found
                with pytest.raises(ComposeNotFoundError) as exc_info:
                    get_compose_command()

                error_msg = str(exc_info.value)
                assert "Docker Compose is not available" in error_msg
                assert "Troubleshooting:" in error_msg
                assert "docker compose version" in error_msg
                assert "Installation options:" in error_msg

    def test_handles_v2_timeout(self):
        """Test handling of timeout when checking v2."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=5)):
            with patch("shutil.which", return_value="/usr/bin/docker-compose"):
                result = get_compose_command()

                # Should fall back to v1
                assert result == ["docker-compose"]

    def test_handles_docker_not_found(self):
        """Test handling when docker binary is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            with patch("shutil.which", return_value="/usr/bin/docker-compose"):
                result = get_compose_command()

                # Should fall back to v1
                assert result == ["docker-compose"]

    def test_caches_result(self):
        """Test that the compose command is cached after first detection."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            # First call
            result1 = get_compose_command()
            # Second call
            result2 = get_compose_command()

            assert result1 == result2 == ["docker", "compose"]
            # subprocess.run should only be called once due to caching
            assert mock_run.call_count == 1

    def test_logs_v2_detection(self, caplog):
        """Test that v2 detection is logged."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            import logging

            with caplog.at_level(logging.INFO):
                get_compose_command()

            assert "Using Docker Compose v2 (docker compose)" in caplog.text

    def test_logs_v1_detection(self, caplog):
        """Test that v1 detection is logged."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/docker-compose"):
                import logging

                with caplog.at_level(logging.INFO):
                    get_compose_command()

                assert "Using Docker Compose v1 (docker-compose)" in caplog.text


class TestComposeCmd:
    """Tests for compose_cmd function."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset the compose command cache before each test."""
        reset_compose_command_cache()
        yield
        reset_compose_command_cache()

    def test_builds_v2_command(self):
        """Test building command with v2."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = compose_cmd("-f", "/path/to/compose.yml", "up", "-d")

            assert result == ["docker", "compose", "-f", "/path/to/compose.yml", "up", "-d"]

    def test_builds_v1_command(self):
        """Test building command with v1."""
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/docker-compose"):
                result = compose_cmd("-f", "/path/to/compose.yml", "up", "-d")

                assert result == [
                    "docker-compose",
                    "-f",
                    "/path/to/compose.yml",
                    "up",
                    "-d",
                ]

    def test_empty_args(self):
        """Test compose_cmd with no additional arguments."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = compose_cmd()

            assert result == ["docker", "compose"]

    def test_single_arg(self):
        """Test compose_cmd with single argument."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = compose_cmd("version")

            assert result == ["docker", "compose", "version"]

    def test_complex_command(self):
        """Test compose_cmd with complex arguments."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = compose_cmd(
                "-f",
                "/opt/ciris/agents/test/docker-compose.yml",
                "up",
                "-d",
                "--pull",
                "always",
                "--force-recreate",
            )

            assert result == [
                "docker",
                "compose",
                "-f",
                "/opt/ciris/agents/test/docker-compose.yml",
                "up",
                "-d",
                "--pull",
                "always",
                "--force-recreate",
            ]


class TestResetCache:
    """Tests for reset_compose_command_cache function."""

    def test_reset_clears_cache(self):
        """Test that reset_compose_command_cache clears the cached value."""
        # Set up a cached value
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            # First call caches the result
            get_compose_command()

        # Reset the cache
        reset_compose_command_cache()

        # Verify cache is cleared
        assert compose_module._compose_command is None

    def test_reset_allows_redetection(self):
        """Test that after reset, the command is re-detected."""
        # First detection: v2
        mock_result_v2 = MagicMock()
        mock_result_v2.returncode = 0

        with patch("subprocess.run", return_value=mock_result_v2):
            result1 = get_compose_command()
            assert result1 == ["docker", "compose"]

        # Reset cache
        reset_compose_command_cache()

        # Second detection: v1 (simulating environment change)
        mock_result_v1 = MagicMock()
        mock_result_v1.returncode = 1

        with patch("subprocess.run", return_value=mock_result_v1):
            with patch("shutil.which", return_value="/usr/bin/docker-compose"):
                result2 = get_compose_command()
                assert result2 == ["docker-compose"]
